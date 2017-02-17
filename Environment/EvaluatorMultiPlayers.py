# -*- coding: utf-8 -*-
""" Evaluator class to wrap and run the simulations, for the multi-players case. """
from __future__ import print_function, division

__author__ = "Lilian Besson"
__version__ = "0.1"

# Generic imports
from copy import deepcopy
from re import search
import random
# Scientific imports
import numpy as np
import matplotlib.pyplot as plt
try:
    import joblib
    USE_JOBLIB = True
except ImportError:
    print("joblib not found. Install it from pypi ('pip install joblib') or conda.")
    USE_JOBLIB = False
# Local imports
from .plotsettings import BBOX_INCHES, signature, maximizeWindow, palette, makemarkers, add_percent_formatter, wraptext, wraplatex
from .ResultMultiPlayers import ResultMultiPlayers
from .MAB import MAB
from .CollisionModels import defaultCollisionModel


# --- Class EvaluatorMultiPlayers

class EvaluatorMultiPlayers(object):
    """ Evaluator class to run the simulations, for the multi-players case.
    """

    def __init__(self, configuration):
        # Configuration
        self.cfg = configuration
        # Attributes
        self.nbPlayers = len(self.cfg['players'])
        print("Number of players in the multi-players game:", self.nbPlayers)  # DEBUG
        self.horizon = self.cfg['horizon']
        print("Time horizon:", self.horizon)  # DEBUG
        self.repetitions = self.cfg['repetitions']
        print("Number of repetitions:", self.repetitions)  # DEBUG
        self.delta_t_save = self.cfg['delta_t_save']
        print("Sampling rate DELTA_T_SAVE:", self.delta_t_save)  # DEBUG
        self.duration = int(self.horizon / self.delta_t_save)
        self.collisionModel = self.cfg.get('collisionModel', defaultCollisionModel)
        print("Using collision model:", self.collisionModel.__name__)  # DEBUG
        print("  Detail:", self.collisionModel.__doc__)  # DEBUG
        # Flags
        self.finalRanksOnAverage = self.cfg.get('finalRanksOnAverage', True)
        self.averageOn = self.cfg.get('averageOn', 5e-3)
        self.useJoblib = USE_JOBLIB and self.cfg['n_jobs'] != 1
        # Internal object memory
        self.envs = []
        self.players = []
        self.__initEnvironments__()
        # Internal vectorial memory
        self.rewards = dict()
        # self.rewardsSquared = dict()
        self.pulls = dict()
        self.allPulls = dict()
        self.collisions = dict()
        self.NbSwitchs = dict()
        self.BestArmPulls = dict()
        self.FreeTransmissions = dict()
        print("Number of environments to try:", len(self.envs))  # DEBUG
        for envId in range(len(self.envs)):  # Zeros everywhere
            self.rewards[envId] = np.zeros((self.nbPlayers, self.duration))
            # self.rewardsSquared[envId] = np.zeros((self.nbPlayers, self.duration))
            self.pulls[envId] = np.zeros((self.nbPlayers, self.envs[envId].nbArms))
            self.allPulls[envId] = np.zeros((self.nbPlayers, self.envs[envId].nbArms, self.duration))
            self.collisions[envId] = np.zeros((self.envs[envId].nbArms, self.duration))
            self.NbSwitchs[envId] = np.zeros((self.nbPlayers, self.duration))
            self.BestArmPulls[envId] = np.zeros((self.nbPlayers, self.duration))
            self.FreeTransmissions[envId] = np.zeros((self.nbPlayers, self.duration))
        # To speed up plotting
        self.times = np.arange(1, 1 + self.horizon, self.delta_t_save)
        # self.subtimes = np.arange(1, 1 + self.duration)

    # --- Init methods

    def __initEnvironments__(self):
        for armType in self.cfg['environment']:
            self.envs.append(MAB(armType))

    def __initPlayers__(self, env):
        for playerId, player in enumerate(self.cfg['players']):
            print("- Adding player #{} = {} ...".format(playerId + 1, player))  # DEBUG
            if isinstance(player, dict):  # Either the 'player' is a config dict
                print("  Creating this player from a dictionnary 'player' = {} ...".format(player))  # DEBUG
                self.players.append(player['archtype'](env.nbArms, **player['params']))
            else:  # Or already a player object
                print("  Using this already created player 'player' = {} ...".format(player))  # DEBUG
                self.players.append(player)

    # --- Start computation

    def startAllEnv(self):
        for envId, env in enumerate(self.envs):
            self.startOneEnv(envId, env)

    # @profile  # DEBUG with kernprof (cf. https://github.com/rkern/line_profiler#kernprof
    def startOneEnv(self, envId, env):
        print("\nEvaluating environment:", repr(env))  # DEBUG
        self.players = []
        self.__initPlayers__(env)
        if self.useJoblib:
            seeds = np.random.randint(low=0, high=100 * self.repetitions, size=self.repetitions)
            results = joblib.Parallel(n_jobs=self.cfg['n_jobs'], verbose=self.cfg['verbosity'])(
                joblib.delayed(delayed_play)(env, self.players, self.horizon, self.collisionModel, delta_t_save=self.delta_t_save, seed=seeds[i])
                for i in range(self.repetitions)
            )
        else:
            results = []
            for _ in range(self.repetitions):
                r = delayed_play(env, self.players, self.horizon, self.collisionModel, delta_t_save=self.delta_t_save)
                results.append(r)
        # Get the position of the best arms
        env = self.envs[envId]
        means = np.array([arm.mean() for arm in env.arms])
        bestarm = np.max(means)
        index_bestarm = np.nonzero(np.isclose(means, bestarm))[0]
        # Get and merge the results from all the 'repetitions'
        # FIXME having this list of results consumes too much RAM !
        for r in results:
            self.rewards[envId] += np.cumsum(r.rewards, axis=1)
            # self.rewardsSquared[envId] += np.cumsum(r.rewards ** 2, axis=1)
            # self.rewardsSquared[envId] += np.cumsum(r.rewardsSquared, axis=1)
            self.pulls[envId] += r.pulls
            self.allPulls[envId] += r.allPulls
            self.collisions[envId] += r.collisions
            for playerId in range(self.nbPlayers):
                self.NbSwitchs[envId][playerId, 1:] += (np.diff(r.choices[playerId, :]) != 0)
                self.BestArmPulls[envId][playerId, :] += np.cumsum(np.in1d(r.choices[playerId, :], index_bestarm))
                # FIXME there is probably a bug in this computation
                self.FreeTransmissions[envId][playerId, :] += np.array([r.choices[playerId, t] not in r.collisions[:, t] for t in range(self.duration)])

    # --- Getter methods

    def getPulls(self, playerId, environmentId=0):
        return self.pulls[environmentId][playerId, :] / float(self.repetitions)

    def getAllPulls(self, playerId, armId, environmentId=0):
        return self.allPulls[environmentId][playerId, armId, :] / float(self.repetitions)

    def getNbSwitchs(self, playerId, environmentId=0):
        return self.NbSwitchs[environmentId][playerId, :] / float(self.repetitions)

    def getBestArmPulls(self, playerId, environmentId=0):
        # We have to divide by a arange() = cumsum(ones) to get a frequency
        return self.BestArmPulls[environmentId][playerId, :] / (float(self.repetitions) * self.times)

    def getFreeTransmissions(self, playerId, environmentId=0):
        return self.FreeTransmissions[environmentId][playerId, :] / float(self.repetitions)

    def getCollisions(self, armId, environmentId=0):
        return self.collisions[environmentId][armId, :] / float(self.repetitions)

    def getRewards(self, playerId, environmentId=0):
        return self.rewards[environmentId][playerId, :] / float(self.repetitions)

    def getRegretMean(self, playerId, environmentId=0):
        """ Warning: this is the centralized regret, for one arm, it does not make much sense in the multi-players setting!
        """
        return (self.times - 1) * self.envs[environmentId].maxArm - self.getRewards(playerId, environmentId)

    def getCentralizedRegret(self, environmentId=0):
        meansArms = np.sort(np.array([arm.mean() for arm in self.envs[environmentId].arms]))
        meansBestArms = meansArms[-self.nbPlayers:]
        sumBestMeans = np.sum(meansBestArms)
        # FIXED how to count it when there is more players than arms ?
        # FIXME it depend on the collision model !
        if self.envs[environmentId].nbArms < self.nbPlayers:
            # sure to have collisions, then the best strategy is to put all the collisions in the worse arm
            worseArm = np.min(meansArms)
            sumBestMeans -= worseArm  # This count the collisions
        averageBestRewards = (self.times - 1) * sumBestMeans
        # And for the actual rewards, the collisions are counted in the rewards logged in self.getRewards
        actualRewards = sum(self.getRewards(playerId, environmentId) for playerId in range(self.nbPlayers))
        return averageBestRewards - actualRewards

    # --- Plotting methods

    # Plotting decentralized (vectorial) rewards
    def plotRewards(self, environmentId=0, savefig=None, semilogx=False):
        plt.figure()
        ymin = 0
        colors = palette(self.nbPlayers)
        markers = makemarkers(self.nbPlayers)
        X = self.times - 1
        cumRewards = np.zeros((self.nbPlayers, self.duration))
        for i, player in enumerate(self.players):
            label = 'Player #{}: {}'.format(i + 1, _extract(str(player)))
            Y = self.getRewards(i, environmentId)
            cumRewards[i, :] = Y
            ymin = min(ymin, np.min(Y))  # XXX Should be smarter
            if semilogx:
                plt.semilogx(X, Y, label=label, color=colors[i], marker=markers[i], markevery=(i / 50., 0.1))
            else:
                plt.plot(X, Y, label=label, color=colors[i], marker=markers[i], markevery=(i / 50., 0.1))
        # TODO add std
        plt.legend(loc='best', numpoints=1, fancybox=True, framealpha=0.8)  # http://matplotlib.org/users/recipes.html#transparent-fancy-legends
        plt.xlabel("Time steps $t = 1 .. T$, horizon $T = {}${}".format(self.horizon, signature))
        ymax = max(plt.ylim()[1], 1.03)  # XXX no that's weird !
        plt.ylim(ymin, ymax)
        plt.ylabel("Cumulative personal reward $r_t$ (not centralized)")
        plt.title("Multi-players $M = {}$ (collision model: {}):\nPersonal reward for each player, averaged ${}$ times\n{} arms: ${}$".format(self.nbPlayers, self.collisionModel.__name__, self.repetitions, self.envs[environmentId].nbArms, self.envs[environmentId].reprarms(self.nbPlayers)))
        maximizeWindow()
        if savefig is not None:
            print("Saving to", savefig, "...")  # DEBUG
            plt.savefig(savefig, bbox_inches=BBOX_INCHES)
        if self.cfg['showplot']: plt.show()
        # DONE compute a certain measure of "fairness", from these personal rewards
        plt.figure()
        amplitudeRewards = (np.max(cumRewards, axis=0) - np.min(cumRewards, axis=0)) / np.max(cumRewards, axis=0)
        plt.ylim(0, 1)
        add_percent_formatter("yaxis", 1.0)
        if semilogx:
            plt.semilogx(X[2:], amplitudeRewards[2:], '+-')
        else:
            plt.plot(X[2:], amplitudeRewards[2:], '+-')
        plt.legend(loc='best', numpoints=1, fancybox=True, framealpha=0.8)  # http://matplotlib.org/users/recipes.html#transparent-fancy-legends
        plt.xlabel("Time steps $t = 1 .. T$, horizon $T = {}$\n{}{}".format(self.horizon, self.strPlayers(), signature))
        plt.ylabel("Centralized measure of (relative) fairness for cumulative rewards\n(rewards best player - rewards worst player) / best rewards")
        plt.title("Multi-players $M = {}$ (collision model: {}):\nCentralized measure of fairness, averaged ${}$ times\n{} arms: ${}$".format(self.nbPlayers, self.collisionModel.__name__, self.repetitions, self.envs[environmentId].nbArms, self.envs[environmentId].reprarms(self.nbPlayers)))
        maximizeWindow()
        if savefig is not None:
            savefig = savefig.replace('main', 'main_Fairness')
            print("Saving to", savefig, "...")  # DEBUG
            plt.savefig(savefig, bbox_inches=BBOX_INCHES)
        if self.cfg['showplot']: plt.show()

    # Plotting centralized regret (sum)
    def plotRegretCentralized(self, environmentId=0, savefig=None, semilogx=False, normalized=False):
        X = self.times - 1
        Y = self.getCentralizedRegret(environmentId)
        if normalized:
            Y /= np.log(2 + X)   # XXX prevent /0
        meanY = np.mean(Y)
        plt.figure()
        if semilogx:
            plt.semilogx(X, Y, 'r-', marker='+', label="{}umulated centralized regret".format("Normalized c" if normalized else "C"))
            # We plot a horizontal line ----- at the mean regret
            plt.semilogx(X, meanY * np.ones_like(X), 'r--', label="Mean cumulated centralized regret = ${:.3g}$".format(meanY))
        else:
            plt.plot(X, Y, 'r-', marker='+', label="{}umulated centralized regret".format("Normalized c" if normalized else "C"))
            # We plot a horizontal line ----- at the mean regret
            plt.plot(X, meanY * np.ones_like(X), 'r--', label="Mean cumulated centralized regret = ${:.3g}$".format(meanY))
        # TODO add std
        lowerbound, anandkumar_lowerbound = self.envs[environmentId].lowerbound_multiplayers(self.nbPlayers)
        print(" - Our lowerbound = {:.3g},\n - anandkumar_lowerbound = {:.3g}".format(lowerbound, anandkumar_lowerbound))  # DEBUG
        # We also plot our lower bound
        if normalized:
            plt.plot(X, lowerbound * np.ones_like(X), 'k-', label="Kaufmann & Besson lower bound = ${:.3g}$".format(lowerbound), lw=3)
            plt.plot(X, anandkumar_lowerbound * np.ones_like(X), 'k:', label="Anandkumar lower bound = ${:.3g}$".format(anandkumar_lowerbound), lw=3)
        else:
            plt.plot(X, lowerbound * np.log(2 + X), 'k-', label="Kaufmann & Besson lower bound = ${:.3g}$".format(lowerbound), lw=3)
            plt.plot(X, anandkumar_lowerbound * np.log(2 + X), 'k:', label="Anandkumar lower bound = ${:.3g}$".format(anandkumar_lowerbound), lw=3)
        # Labels and legends
        plt.legend(loc='best', numpoints=1, fancybox=True, framealpha=0.8)  # http://matplotlib.org/users/recipes.html#transparent-fancy-legends
        plt.xlabel("Time steps $t = 1 .. T$, horizon $T = {}$\n{}{}".format(self.horizon, self.strPlayers(), signature))
        plt.ylabel("{}umulative centralized regret $R_t$".format("Normalized c" if normalized else "C"))
        plt.title("Multi-players $M = {}$ (collision model: {}):\n{}umulated centralized regret, averaged ${}$ times\n{} arms: ${}$".format(self.nbPlayers, self.collisionModel.__name__, "normalized c" if normalized else "C", self.repetitions, self.envs[environmentId].nbArms, self.envs[environmentId].reprarms(self.nbPlayers)))
        maximizeWindow()
        if savefig is not None:
            print("Saving to", savefig, "...")  # DEBUG
            plt.savefig(savefig, bbox_inches=BBOX_INCHES)
        if self.cfg['showplot']: plt.show()

    # Plotting cumulated number of switchs (switching costs)
    def plotNbSwitchs(self, environmentId=0, savefig=None, semilogx=False, cumulated=False):
        X = self.times - 1
        plt.figure()
        ymin = 0
        colors = palette(self.nbPlayers)
        markers = makemarkers(self.nbPlayers)
        for i, player in enumerate(self.players):
            label = 'Player #{}: {}'.format(i + 1, str(player))
            Y = self.getNbSwitchs(i, environmentId)
            if cumulated:
                Y = np.cumsum(Y)
            ymin = min(ymin, np.min(Y))  # XXX Should be smarter
            if semilogx:
                plt.semilogx(X, Y, label=label, color=colors[i], marker=markers[i], markevery=(i / 50., 0.1), linestyle='-' if cumulated else '')
            else:
                plt.plot(X, Y, label=label, color=colors[i], marker=markers[i], markevery=(i / 50., 0.1), linestyle='-' if cumulated else '')
        plt.legend(loc='best' if cumulated else 'upper right', numpoints=1, fancybox=True, framealpha=0.8)  # http://matplotlib.org/users/recipes.html#transparent-fancy-legends
        plt.xlabel("Time steps $t = 1 .. T$, horizon $T = {}${}".format(self.horizon, signature))
        ymax = max(plt.ylim()[1], 1)
        plt.ylim(ymin, ymax)
        if not cumulated:
            add_percent_formatter("yaxis", 1.0)
        plt.ylabel("{} of switches by player".format("Cumulated Number" if cumulated else "Frequency"))
        plt.title("Multi-players $M = {}$ (collision model: {}):\n{}number of switches for each player, averaged ${}$ times\n{} arms: ${}$".format(self.nbPlayers, self.collisionModel.__name__, "Cumulated " if cumulated else "", self.repetitions, self.envs[environmentId].nbArms, self.envs[environmentId].reprarms(self.nbPlayers)))
        maximizeWindow()
        if savefig is not None:
            print("Saving to", savefig, "...")  # DEBUG
            plt.savefig(savefig, bbox_inches=BBOX_INCHES)
        if self.cfg['showplot']: plt.show()

    def plotBestArmPulls(self, environmentId=0, savefig=None):
        X = self.times - 1
        plt.figure()
        colors = palette(self.nbPlayers)
        markers = makemarkers(self.nbPlayers)
        for i, player in enumerate(self.players):
            Y = self.getBestArmPulls(i, environmentId)
            plt.plot(X, Y, label=str(player), color=colors[i], marker=markers[i], markevery=(i / 50., 0.1))
        plt.legend(loc='best', numpoints=1, fancybox=True, framealpha=0.8)  # http://matplotlib.org/users/recipes.html#transparent-fancy-legends
        plt.xlabel("Time steps $t = 1 .. T$, horizon $T = {}${}".format(self.horizon, signature))
        plt.ylim(-0.03, 1.03)
        add_percent_formatter("yaxis", 1.0)
        plt.ylabel("Frequency of pulls of the optimal arm")
        plt.title("Multi-players $M = {}$ (collision model: {}):\nBest arm pulls frequency for each players, averaged ${}$ times\n{} arms: ${}$".format(self.nbPlayers, self.collisionModel.__name__, self.cfg['repetitions'], self.envs[environmentId].nbArms, self.envs[environmentId].reprarms(self.nbPlayers)))
        maximizeWindow()
        if savefig is not None:
            print("Saving to", savefig, "...")  # DEBUG
            plt.savefig(savefig, bbox_inches=BBOX_INCHES)
        if self.cfg['showplot']: plt.show()

    def plotAllPulls(self, environmentId=0, savefig=None, cumulated=True, normalized=False):
        X = self.times - 1
        mainfig = savefig
        colors = palette(self.nbPlayers)
        markers = makemarkers(self.nbPlayers)
        for armId in range(self.envs[environmentId].nbArms):
            plt.figure()
            for playerId, player in enumerate(self.players):
                Y = self.getAllPulls(playerId, armId, environmentId)
                if cumulated:
                    Y = np.cumsum(Y)
                if normalized:
                    Y /= 1 + X
                plt.plot(X, Y, label=str(player), color=colors[playerId], linestyle='', marker=markers[playerId], markevery=(playerId / 50., 0.1))
            plt.legend(loc='best', numpoints=1, fancybox=True, framealpha=0.8)  # http://matplotlib.org/users/recipes.html#transparent-fancy-legends
            plt.xlabel("Time steps $t = 1 .. T$, horizon $T = {}${}".format(self.horizon, signature))
            s = ("Normalized " if normalized else "") + ("Cumulated number" if cumulated else "Frequency")
            plt.ylabel("{} of pulls of the arm #{}".format(s, armId + 1))
            plt.title("Multi-players $M = {}$ (collision model: {}):\n{} of pulls of the arm #{} for each players, averaged ${}$ times\n{} arms: ${}$".format(self.nbPlayers, self.collisionModel.__name__, s.lower(), armId + 1, self.cfg['repetitions'], self.envs[environmentId].nbArms, self.envs[environmentId].reprarms(self.nbPlayers)))
            maximizeWindow()
            if savefig is not None:
                savefig = mainfig.replace("AllPulls", "AllPulls_Arm{}".format(armId + 1))
                print("Saving to", savefig, "...")  # DEBUG
                plt.savefig(savefig, bbox_inches=BBOX_INCHES)
            if self.cfg['showplot']: plt.show()

    def plotFreeTransmissions(self, environmentId=0, savefig=None, cumulated=False):
        X = self.times - 1
        plt.figure()
        colors = palette(self.nbPlayers)
        for i, player in enumerate(self.players):
            Y = self.getFreeTransmissions(i, environmentId)
            if cumulated:
                Y = np.cumsum(Y)
            plt.plot(X, Y, '.', label=str(player), color=colors[i], linewidth=1, markersize=1)
            # should only plot with markers
        plt.legend(loc='best', numpoints=1, fancybox=True, framealpha=0.8)  # http://matplotlib.org/users/recipes.html#transparent-fancy-legends
        plt.xlabel("Time steps $t = 1 .. T$, horizon $T = {}${}".format(self.horizon, signature))
        plt.ylim(-0.03, 1.03)
        add_percent_formatter("yaxis", 1.0)
        plt.ylabel("{}Transmission on a free channel".format("Cumulated " if cumulated else ""))
        plt.title("Multi-players $M = {}$ (collision model: {}):\n{}free transmission for each players, averaged ${}$ times\n{} arms: ${}$".format(self.nbPlayers, self.collisionModel.__name__, "Cumulated " if cumulated else "", self.cfg['repetitions'], self.envs[environmentId].nbArms, self.envs[environmentId].reprarms(self.nbPlayers)))
        maximizeWindow()
        if savefig is not None:
            print("Saving to", savefig, "...")  # DEBUG
            plt.savefig(savefig, bbox_inches=BBOX_INCHES)
        if self.cfg['showplot']: plt.show()

    # TODO I should plot the evolution of the occupation ratio of each channel, as a function of time
    # Starting from the average occupation (by primary users), as given by [1 - arm.mean()], it should increase occupation[arm] when users chose it
    # The reason/idea is that good arms (low occupation ration) are pulled a lot, thus becoming not as available as they seemed

    def plotNbCollisions(self, environmentId=0, savefig=None, cumulated=False):
        X = self.times - 1
        Y = np.zeros(self.duration)
        for armId in range(self.envs[environmentId].nbArms):
            # Y += (self.getCollisions(armId, environmentId) >= 1)
            Y += self.getCollisions(armId, environmentId)
        plt.figure()
        if cumulated:
            Y = np.cumsum(Y)
        else:
            plt.ylim(-0.03, 1.03)
            add_percent_formatter("yaxis", 1.0)
        Y /= self.nbPlayers  # XXX To normalized the count?
        # Start the figure
        plt.xlabel("Time steps $t = 1 .. T$, horizon $T = {}$\n{}{}".format(self.horizon, self.strPlayers(), signature))
        plt.ylabel("{} of collisions".format("Cumulated number" if cumulated else "Frequency"))
        plt.plot(X, Y, '-' if cumulated else '.')
        plt.legend(loc='best', fancybox=True, framealpha=0.8)  # http://matplotlib.org/users/recipes.html#transparent-fancy-legends
        plt.title("Multi-players $M = {}$ (collision model: {}):\n{}of collisions, averaged ${}$ times\n{} arms: ${}$".format(self.nbPlayers, self.collisionModel.__name__, "cumulated number " if cumulated else "frequency ", self.cfg['repetitions'], self.envs[environmentId].nbArms, self.envs[environmentId].reprarms(self.nbPlayers)))
        maximizeWindow()
        if savefig is not None:
            print("Saving to", savefig, "...")  # DEBUG
            plt.savefig(savefig, bbox_inches=BBOX_INCHES)
        if self.cfg['showplot']: plt.show()

    def plotFrequencyCollisions(self, environmentId=0, savefig=None, piechart=True):
        nbArms = self.envs[environmentId].nbArms
        Y = np.zeros(1 + nbArms)  # One extra arm for "no collision"
        labels = [''] * (1 + nbArms)  # Empty labels
        colors = palette(1 + nbArms)  # Get colors
        # All the other arms
        for armId, arm in enumerate(self.envs[environmentId].arms):
            # Y[armId] = np.sum(self.getCollisions(armId, environmentId) >= 1)  # XXX no, we should not count just the fact that there were collisions, but instead count all collisions
            Y[armId] = np.sum(self.getCollisions(armId, environmentId))
            labels[armId] = "#${}$: ${}$ (${:.1%}$$\%$)".format(armId, repr(arm), Y[armId])
        Y /= (self.horizon * self.nbPlayers)
        assert 0 <= np.sum(Y) <= 1, "Error: the sum of collisions = {}, averaged by horizon and nbPlayers, cannot be outside of [0, 1] ...".format(np.sum(Y))
        for armId, arm in enumerate(self.envs[environmentId].arms):
            print("  - For {},\tfrequency of collisions is {:g}  ...".format(labels[armId], Y[armId]))  # DEBUG
            if Y[armId] < 5e-3:  # Do not display small slices
                labels[armId] = ''
        if np.isclose(np.sum(Y), 0):
            print("==> No collisions to plot ... Stopping now  ...")  # DEBUG
            # return  # XXX
        # Special arm: no collision
        Y[-1] = 1 - np.sum(Y) if np.sum(Y) < 1 else 0
        labels[-1] = "No collision (${:.1%}$$\%$)".format(Y[-1]) if Y[-1] > 1e-4 else ''
        colors[-1] = 'lightgrey'
        # Start the figure
        plt.figure()
        if piechart:
            plt.xlabel("{}{}".format(self.strPlayers(), signature))
            plt.axis('equal')
            plt.pie(Y, labels=labels, colors=colors, explode=[0.07] * len(Y), startangle=45)
        else:  # TODO do an histogram instead of this piechart?
            plt.hist(Y, bins=len(Y), colors=colors)
            # XXX if this is not enough, do the histogram/bar plot manually, and add labels as texts
        plt.legend(loc='best', fancybox=True, framealpha=0.8)  # http://matplotlib.org/users/recipes.html#transparent-fancy-legends
        plt.title("Multi-players $M = {}$ (collision model: {}):\nFrequency of collision for each arm, averaged ${}$ times\n{} arms: ${}$".format(self.nbPlayers, self.collisionModel.__name__, self.cfg['repetitions'], self.envs[environmentId].nbArms, self.envs[environmentId].reprarms(self.nbPlayers)))
        maximizeWindow()
        if savefig is not None:
            print("Saving to", savefig, "...")  # DEBUG
            plt.savefig(savefig, bbox_inches=BBOX_INCHES)
        if self.cfg['showplot']: plt.show()

    def printFinalRanking(self, environmentId=0):
        assert 0 < self.averageOn < 1, "Error, the parameter averageOn of a EvaluatorMultiPlayers classs has to be in (0, 1) strictly, but is = {} here ...".format(self.averageOn)
        print("\nFinal ranking for this environment #{} :".format(environmentId))  # DEBUG
        lastY = np.zeros(self.nbPlayers)
        for i, player in enumerate(self.players):
            Y = self.getRewards(i, environmentId)
            if self.finalRanksOnAverage:
                lastY[i] = np.mean(Y[-int(self.averageOn * self.duration)])   # get average value during the last averageOn% of the iterations
            else:
                lastY[i] = Y[-1]  # get the last value
        # Sort lastY and give ranking
        index_of_sorting = np.argsort(-lastY)  # Get them by INCREASING rewards, not decreasing regrets
        for i, k in enumerate(index_of_sorting):
            player = self.players[k]
            print("- Player #{}, '{}'\twas ranked\t{} / {} for this simulation (last rewards = {:g}).".format(k + 1, str(player), i + 1, self.nbPlayers, lastY[k]))  # DEBUG
        return lastY, index_of_sorting

    def strPlayers(self):
        listStrPlayers = [_extract(str(player)) for player in self.players]
        if len(set(listStrPlayers)) == 1:  # Unique user
            text = '{} x {}'.format(self.nbPlayers, listStrPlayers[0])
        else:
            text = ', '.join(listStrPlayers)
        text = wraptext(text)
        text = '{} players: {}'.format(self.nbPlayers, text)
        return text


# Helper function for the parallelization
# @profile  # DEBUG with kernprof (cf. https://github.com/rkern/line_profiler#kernprof
def delayed_play(env, players, horizon, collisionModel,
                 delta_t_save=1, seed=None):
    # XXX Try to give a unique seed to random & numpy.random for each call of this function
    try:
        np.random.seed(seed)
        random.seed(seed)
    except SystemError:
        print("Warning: setting random.seed and np.random.seed seems to not be available. Are you using Windows?")  # XXX
    # We have to deepcopy because this function is Parallel-ized
    env = deepcopy(env)
    nbArms = env.nbArms
    players = deepcopy(players)
    horizon = deepcopy(horizon)
    nbPlayers = len(players)
    # random_arm_orders = [np.random.permutation(nbArms) for i in range(nbPlayers)]
    # Start game
    for player in players:
        player.startGame()
    # Store results
    result = ResultMultiPlayers(env.nbArms, horizon, nbPlayers, delta_t_save=delta_t_save)
    rewards = np.zeros(nbPlayers)
    choices = np.zeros(nbPlayers, dtype=int)
    pulls = np.zeros((nbPlayers, nbArms), dtype=int)
    collisions = np.zeros(nbArms, dtype=int)
    for t in range(horizon):
        # Reset the array, faster than reallocating them!
        rewards.fill(0)
        pulls.fill(0)
        collisions.fill(0)
        # Every player decides which arm to pull
        for i, player in enumerate(players):
            # FIXME here, the environment should apply ONCE a random permutation to each player, in order for the non-modified UCB-like algorithms to work fine in case of collisions (their initial exploration phase is non-random hence leading to only collisions in the first steps, and ruining the performance)
            # choices[i] = random_arm_orders[i][player.choice()]
            choices[i] = player.choice()
            # print(" Round t = \t{}, player \t#{}/{} ({}) \tchose : {} ...".format(t, i + 1, len(players), player, choices[i]))  # DEBUG
        # Then we decide if there is collisions and what to do why them
        # XXX It is here that the player may receive a reward, if there is no collisions
        collisionModel(t, env.arms, players, choices, rewards, pulls, collisions)
        # Finally we store the results
        if t % delta_t_save == 0:
            # if delta_t_save > 1: print("t =", t, "delta_t_save =", delta_t_save, " : saving ...")  # DEBUG
            result.store(t, choices, rewards, pulls, collisions)

    # # XXX Prints the ranks
    # ranks = [player.rank if hasattr(player, 'rank') else None for player in players]
    # if len(set(ranks)) != nbPlayers:
    #     for (player, rank) in zip(players, ranks):
    #         if rank:
    #             print(" - End of one game, rhoRand player {} had rank {} ...".format(player, rank))
    # else:
    #     if set(ranks) != {None}:
    #         print(" - End of one game, rhoRand found orthogonal ranks: ranks = {} ...".format(ranks))
    return result


# Utility function...
def _extract(text):
    """ Extract the str of a player, if it is a child, printed as '#[0-9]+<...>' --> ... """
    try:
        m = search("<[^>]+>", text).group(0)
        if m[0] == '<' and m[-1] == '>':
            return m[1:-1]  # Extract text between < ... >
        else:
            return text
    except AttributeError:
        return text

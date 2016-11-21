# -*- coding: utf-8 -*-
""" Evaluator class to wrap and run the simulations."""
from __future__ import print_function

__author__ = "Lilian Besson"
__version__ = "0.2"

from copy import deepcopy
import numpy as np
import matplotlib.pyplot as plt
try:
    import joblib
    USE_JOBLIB = True
except ImportError:
    print("joblib not found. Install it from pypi ('pip install joblib') or conda.")
    USE_JOBLIB = False

from .Result import Result
from .MAB import MAB


class Evaluator:
    """ Evaluator class to run the simulations."""

    def __init__(self, configuration):
        self.cfg = configuration
        self.envs = []
        self.policies = []
        self.__initEnvironments__()
        self.rewards = np.zeros((len(self.cfg['policies']),
                                 len(self.envs), self.cfg['horizon']))
        self.pulls = dict()
        for env in range(len(self.envs)):
            self.pulls[env] = np.zeros((len(self.cfg['policies']), self.envs[env].nbArms))
        print("Number of algorithms to compare:", len(self.cfg['policies']))
        print("Number of environments to try:", len(self.envs))
        print("Time horizon:", self.cfg['horizon'])
        print("Number of repetitions:", self.cfg['repetitions'])

    def __initEnvironments__(self):
        for armType in self.cfg['environment']:
            self.envs.append(MAB(armType))

    def __initPolicies__(self, env):
        for policy in self.cfg['policies']:
            print("policy =", policy)  # DEBUG
            self.policies.append(policy['archtype'](env.nbArms,
                                                    **policy['params']))

    def start(self):
        for envId, env in enumerate(self.envs):
            print("\nEvaluating environment:", repr(env))
            self.policies = []
            self.__initPolicies__(env)
            for polId, policy in enumerate(self.policies):
                print("\n- Evaluating: {} ({}) ...".format(policy, policy.params))
                if USE_JOBLIB:
                    results = joblib.Parallel(n_jobs=self.cfg['n_jobs'], verbose=self.cfg['verbosity'])(
                        joblib.delayed(play)(env, policy, self.cfg['horizon'])
                        for _ in range(self.cfg['repetitions'])
                    )
                else:
                    results = []
                    for _ in range(self.cfg['repetitions']):
                        results.append(play(env, policy, self.cfg['horizon']))
                for result in results:
                    self.rewards[polId, envId, :] += np.cumsum(result.rewards)
                    self.pulls[envId][polId, :] += result.pulls

    def getReward(self, policyId, environmentId):
        return self.rewards[policyId, environmentId, :] / float(self.cfg['repetitions'])

    def getRegret(self, policyId, environmentId):
        horizon = np.arange(self.cfg['horizon'])
        return horizon * self.envs[environmentId].maxArm - self.getReward(policyId, environmentId)

    def plotResults(self, environment, savefig=None):
        plt.figure()
        ymin = 0
        for i, policy in enumerate(self.policies):
            Y = self.getRegret(i, environment)
            ymin = min(ymin, np.min(Y))  # XXX Should be smarter
            # plt.plot(Y, label=str(policy))
            plt.semilogx(Y, label=str(policy))
        plt.legend(loc='upper left')
        plt.grid()
        plt.xlabel("Time steps")
        ymax = plt.ylim()[1]
        # ymin = max(0, ymin)    # prevent a negative ymin
        plt.ylim(ymin, ymax)
        plt.ylabel("Cumulative Regret")
        plt.title("Regrets for different bandit algoritms, averaged {} times\nArms: {}".format(self.cfg['repetitions'], repr(self.cfg['environment'][environment])))
        if savefig is not None:
            print("Saving to", savefig, "...")
            plt.savefig(savefig)
        plt.show()


def play(env, policy, horizon):
    # We have to deepcopy because this function is Parallel-ized
    env = deepcopy(env)
    policy = deepcopy(policy)
    horizon = deepcopy(horizon)

    policy.startGame()
    result = Result(env.nbArms, horizon)
    for t in range(horizon):
        choice = policy.choice()
        reward = env.arms[choice].draw(t)
        policy.getReward(choice, reward)
        result.store(t, choice, reward)
    return result

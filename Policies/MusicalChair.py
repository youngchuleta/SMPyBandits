# -*- coding: utf-8 -*-
""" MusicalChair: implementation of the single-player policy from [A Musical Chair approach, Shamir et al., 2015](https://arxiv.org/abs/1512.02866).

- Each player has 3 states, 1st is random exploration, 2nd is musical chair, 3rd is staying sit
- 1st step
  - Every player tries uniformly an arm for T0 steps, counting the empirical means of each arm, and the number of observed collisions C_T0
  - Finally, N* = nbPlayers is estimated based on nb of collisions C_T0, and the N* best arms are computed from their empirical means
- 2nd step:
  - Every player chose an arm uniformly, among the N* best arms, until she does not encounter collision right after choosing it
  - When an arm was chosen by only one player, she decides to sit on this chair (= arm)
- 3rd step:
  - Every player stays sitted on her chair for the rest of the game
  - ==> constant regret if N* is well estimated and if the estimated N* best arms were correct
  - ==> linear regret otherwise
"""
from __future__ import print_function

__author__ = "Lilian Besson"
__version__ = "0.1"

import numpy as np
from enum import Enum  # For the different states


# --- Functions to compute the optimal choice of Time0 proposed in [Shamir et al., 2015]

def optimalT0(nbArms, epsilon, delta=0.05):
    """ Ch. Theorem 1 of [Shamir et al., 2015](https://arxiv.org/abs/1512.02866).

    >>> optimalT0(2, 0.1, 0.05)     # Just 2 arms !
    18459                           # ==> That's a LOT of steps for just 2 arms!
    >>> optimalT0(17, 0.01, 0.05)   # Constant regret with >95% proba
    27331794                        # ==> That's a LOT of steps!!!
    >>> optimalT0(17, 0.001, 0.05)  # Reasonable value of epsilon
    2733179304                      # ==> That's a LOT of steps!!!
    """
    K = nbArms
    T0_1 = (K / 2.) * np.log(2 * K**2 / delta)
    T0_2 = ((16 * K) / (epsilon**2)) * np.log(4 * K**2 / delta)
    T0_3 = (K**2 * np.log10(2 / delta**2)) / 0.02   # delta**2 or delta_2 ? Typing mistake in their paper
    T0 = max(T0_1, T0_2, T0_3)
    return int(np.ceil(T0))


def boundOnFinalRegret(T0, nbPlayers):
    """ Ch. Theorem 1 of [Shamir et al., 2015](https://arxiv.org/abs/1512.02866).

    >>> boundOnFinalRegret(18459, 2)       # Crazy constant regret!
    36948
    >>> boundOnFinalRegret(27331794, 6)    # Crazy constant regret!!
    163990852
    >>> boundOnFinalRegret(2733179304, 6)  # Crazy constant regret!!
    16399075913
    """
    return T0 * nbPlayers + 2 * np.exp(2) * nbPlayers


# --- Class MusicalChair

State = Enum('State', ['NotStarted', 'InitialPhase', 'MusicalChair', 'Sitted'])


class MusicalChair(object):
    """ MusicalChair: implementation of the single-player policy from [A Musical Chair approach, Shamir et al., 2015](https://arxiv.org/abs/1512.02866).
    """

    def __init__(self, nbArms, Time0=0.25, Time1=None, N=None):  # Named argument to give them in any order
        """
        - nbArms: number of arms.
        - N: number of players to create (in self._players). Warning: each child player should NOT use this knowledge!

        Example:
        >>> nbArms, Time0, Time1, N = 17, 0.1, 10000, 6
        >>> player1 = MusicalChair(nbArms, Time0, Time1, N)

        For multi-players use:
        >>> configuration["players"] = Selfish(NB_PLAYERS, MusicalChair, nbArms, Time0=0.25, Time1=HORIZON, N=NB_PLAYERS).childs
        """
        nbPlayers = N
        assert nbPlayers is None or nbPlayers > 0, "Error, the parameter 'nbPlayers' for MusicalChair class has to be None or > 0."
        self.state = State.NotStarted
        if 0 < Time0 < 1:  # Time0 is a fraction of the horizon Time1
            Time0 = int(Time0 * Time1)  # Lower bound
        elif 1 <= Time0:
            Time0 = int(Time0)
        # Store parameters
        self.nbArms = nbArms
        self.Time0 = Time0
        self.nbPlayers = nbPlayers
        # Internal memory
        self._chair = None  # Not sited yet
        self._cumulatedRewards = np.zeros(nbArms)  # That's the s_i(t) of the paper
        self._nbObservations = np.zeros(nbArms, dtype=int)  # That's the o_i of the paper
        self._A = np.random.permutation(nbArms)  # XXX it will then be of size nbPlayers!
        self._nbCollision = 0  # That's the C_Time0 of the paper
        # Implementation details
        self.t = -1

    def __str__(self):
        # return "MusicalChair(N*: {}, T0: {})".format(self.nbPlayers, self.Time0)  # Use current estimate
        return "MusicalChair(T0: {})".format(self.Time0)  # Use current estimate

    def startGame(self):
        """ Just reinitialize all the internal memory, and decide how to start (state 1 or 2)."""
        self.t = -1  # -1 because t += 1 is done in self.choice()
        self._chair = None  # Not sited yet
        self._cumulatedRewards.fill(0)
        self._nbObservations.fill(0)
        self._A = np.random.permutation(self.nbArms)  # We have to select a random permutation, instead of fill(0), in case the initial phase was too short, the player is not too stupid
        self._nbCollision = 0
        # if nbPlayers is None, start by estimating it to N*, with the initial phase procedure
        if self.nbPlayers is None:
            self.state = State.InitialPhase
        else:  # No need for an initial phase if nbPlayers is known (given)
            self.Time0 = 0
            self.state = State.MusicalChair

    def choice(self):
        """ Chose an arm, as described by the Musical Chair algorithm."""
        self.t += 1
        if self._chair is not None:  # and self.state == State.Sitted:
            # If the player is already sit, nothing to do
            self.state = State.Sitted  # We can stay sitted: no collision right after we sit
            # If we can chose this chair like this, it's because we were already sitted, without seeing a collision
            # print("\n- A MusicalChair player chose arm {} because it's his chair, and time t = {} ...".format(self._chair, self.t))  # DEBUG
            return self._chair
        elif self.state == State.InitialPhase:
            # Play as initial phase: chose a random arm, uniformly among all the K arms
            i = np.random.randint(self.nbArms)
            # print("\n- A MusicalChair player chose a random arm {} among [1,...,{}] as it is in state InitialPhase, and time t = {} ...".format(i, self.nbArms, self.t))  # DEBUG
            return i
        elif self.state == State.MusicalChair:
            # Play as musical chair: chose a random arm, among the M bests
            i = np.random.choice(self._A)  # Random arm among the M bests
            self._chair = i  # Assume that it would be a good chair
            # print("\n- A MusicalChair player chose a random arm i={} of index={} among the {}-best arms in [1,...,{}] as it is in state MusicalChair, and time t = {} ...".format(i, k, self.nbPlayers, self.nbArms, self.t))  # DEBUG
            return i
        else:  # TODO remove this
            raise ValueError("MusicalChair.choice() should never be in this case. Fix this code, quickly!")

    def getReward(self, arm, reward):
        """ Receive a reward on arm of index 'arm', as described by the Musical Chair algorithm.

        - If not collision, receive a reward after pulling the arm.
        """
        # print("- A MusicalChair player receive reward = {} on arm {}, in state {} and time t = {}...".format(reward, arm, self.state, self.t))  # DEBUG
        # If not collision, receive a reward after pulling the arm
        if self.state == State.InitialPhase:
            # Count the observation, update arm cumulated reward
            self._nbObservations[arm] += 1      # One observation of this arm
            self._cumulatedRewards[arm] += reward  # More reward
        # elif self.state in [State.MusicalChair, State.Sitted]:
        #     pass  # Nothing to do in this second phase
        #     # We don't care anymore about rewards in this step

        # And if t = Time0, we are do with the initial phase
        if self.t >= self.Time0 and self.state == State.InitialPhase:
            self.endInitialPhase()

    def endInitialPhase(self):
        # print("\n- A MusicalChair player has to switch from InitialPhase to MusicalChair ...")  # DEBUG
        self.state = State.MusicalChair  # Switch ONCE to state 2
        # First, we compute the empirical means mu_i
        # print("   - self._cumulatedRewards =", self._cumulatedRewards)  # DEBUG
        # print("   - self._nbObservations =", self._nbObservations)  # DEBUG
        empiricalMeans = self._cumulatedRewards / self._nbObservations
        # print("   - empiricalMeans =", empiricalMeans)  # DEBUG
        # Then, we compute the final estimate of N* = nbPlayers
        if self._nbCollision == self.Time0:  # 1st case, we only saw collisions!
            self.nbPlayers = self.nbArms  # Worst case, pessimist estimate of the nb of players
        else:  # 2nd case, we didn't see only collisions
            self.nbPlayers = int(round(1 + np.log((self.Time0 - self._nbCollision) / self.Time0) / np.log(1. - 1. / self.nbArms)))
        # print("   - self.nbPlayers =", self.nbPlayers)  # DEBUG
        # Finally, sort their index by empirical means, decreasing order
        self._A = np.argsort(-empiricalMeans)[:self.nbPlayers]  # FIXED among the best M arms!
        # print("   - self._A =", self._A)  # DEBUG

    def handleCollision(self, arm):
        """ Handle a collision, on arm of index 'arm'.

        - Warning: this method has to be implemented in the collision model, it is NOT implemented in the EvaluatorMultiPlayers.
        """
        # print("- A MusicalChair player saw a collision on arm {}, in state {}, and time t = {} ...".format(arm, self.state, self.t))  # DEBUG
        if self.state == State.InitialPhase:
            # count one more collision in this initial phase (no matter the arm)
            self._nbCollision += 1
        elif self.state == State.MusicalChair:
            assert self._chair is not None, "Error: bug in my code in handleCollision() for MusicalChair class."
            self._chair = None  # Cannot stay sitted here

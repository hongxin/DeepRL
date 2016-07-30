from Agent import Agent
import random
import tensorflow as tf
import numpy as np

import logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


class QAgent(Agent):
    """
    Human-level control through deep reinforcement learning

    Args:
        _model (function): necessary, model to create q func,
                        output's dim should be equal with num of actions
        _env (Env): necessary, env to learn, should be rewritten from Env
        _is_train (bool): default True
        _optimizer (chainer.optimizers): not necessary, if not then func won't be updated
        _replay (Replay): necessary for training
        _gpu (bool): whether to use gpu
        _gamma (float): reward decay
        _batch_size (int): how much tuples to pull from replay
        _epsilon (float): init epsilon, p for choosing randomly
        _epsilon_decay (float): epsilon *= epsilon_decay
        _epsilon_underline (float): epsilon = max(epsilon_underline, epsilon)
        _grad_clip (float): clip grad, 0 is no clip
    """

    def __init__(self, _model, _env, _is_train=True,
                 _optimizer=None, _replay=None,
                 _gpu=False, _gamma=0.99, _batch_size=32,
                 _epsilon=0.5, _epsilon_decay=0.995, _epsilon_underline=0.01,
                 _grad_clip=1.):

        super(QAgent, self).__init__(_is_train, _gpu)

        # set env
        self.env = _env

        with tf.device(self.config.device):
            # create q func
            self.q_func, self.q_vars = _model(self.x_place)

            if self.is_train:
                # create target q func
                self.target_q_func, self.target_q_vars = _model(self.x_place)
                # place for action(one hot), target, weight
                self.action_place = tf.placeholder(tf.float32)
                self.target_place = tf.placeholder(tf.float32)
                self.weight_place = tf.placeholder(tf.float32)
                # get cur action value
                action_value = tf.reduce_sum(
                    self.q_func * self.action_place, 1
                )
                # get err of cur action value and target value
                self.err_list_op = 0.5 * \
                    tf.square(action_value - self.target_place)
                # get total loss, mul with weight, if weight exist
                loss = tf.reduce_mean(self.err_list_op * self.weight_place)
                # compute grads of vars
                self.grads_op = tf.gradients(loss, self.q_vars)

                if _optimizer:
                    # if opt exist, then update vars
                    self.q_grads_place = [
                        tf.placeholder(tf.float32) for _ in self.q_vars
                    ]
                    self.q_opt = _optimizer.apply_gradients([
                        (p, v) for p, v in zip(
                            self.q_grads_place, self.q_vars)
                    ])

                self.replay = _replay

            # init all vars
            self.sess.run(tf.initialize_all_variables())
            # copy params from q func to target
            self.updateTargetFunc()

        self.config.gamma = _gamma
        self.config.batch_size = _batch_size
        self.config.epsilon = _epsilon
        self.config.epsilon_decay = _epsilon_decay
        self.config.epsilon_underline = _epsilon_underline
        self.config.grad_clip = _grad_clip

    def step(self):
        """
        Returns:
            still in game or not
        """
        return super(QAgent, self).step(self.q_func)

    def forward(self, _next_x, _state_list):
        with tf.device(self.config.device):
            # get next outputs, NOT target
            next_output = self.func(self.q_func, _next_x, False)
            # only one head
            next_action = self.env.getBestAction(next_output, _state_list)
            # get next outputs, target
            next_output = self.func(self.target_q_func, _next_x, False)

        return next_output, next_action

    def grad(self, _cur_x, _next_output, _next_action, _batch_tuples, _weights):
        with tf.device(self.config.device):
            # get action data (one hot)
            action_data = np.zeros_like(_next_output)
            for i in range(len(_batch_tuples)):
                action_data[i, _batch_tuples[i].action] = 1.
            # get target data
            target_data = np.zeros((len(_batch_tuples)), np.float32)
            for i in range(len(_batch_tuples)):
                target_value = _batch_tuples[i].reward
                # if not empty position, not terminal state
                if _batch_tuples[i].next_state.in_game:
                    target_value += self.config.gamma * \
                        _next_output[i][_next_action[i]]
                target_data[i] = target_value
            # get weight data
            if _weights is not None:
                weigth_data = _weights
            else:
                weigth_data = np.ones((len(_batch_tuples)), np.float32)

            # get err list [0] and grads [1:]
            ret = self.sess.run(
                [self.err_list_op] + self.grads_op,
                feed_dict={
                    self.x_place: _cur_x,
                    self.action_place: action_data,
                    self.target_place: target_data,
                    self.weight_place: weigth_data,
                }
            )
            # set grads data
            self.q_grads_data = ret[1:]
        # return err_list
        return ret[0]

    def doTrain(self, _batch_tuples, _weights):
        # get inputs from batch
        cur_x = self.getCurInputs(_batch_tuples)
        next_x = self.getNextInputs(_batch_tuples)
        # compute forward
        next_output, next_action = self.forward(
            next_x, [t.next_state for t in _batch_tuples])
        # fill grad
        err_list = self.grad(
            cur_x, next_output, next_action, _batch_tuples, _weights)
        return err_list

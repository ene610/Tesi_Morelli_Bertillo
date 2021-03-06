#@title DDQN PER AGENT
import os
import torch as T
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import numpy as np
import gym
import numpy as np
from gym import wrappers
import os
import shutil
from torch.utils.tensorboard import SummaryWriter

from itertools import count
import random
from torch.autograd import Variable

class Memory:  # stored as ( s, a, r, s_ ) in SumTree
    e = 0.01
    a = 0.8
    beta = 0.3
    beta_increment_per_sampling = 0.0005

    def __init__(self, capacity):
        self.tree = SumTree(capacity)
        self.capacity = capacity

    def _get_priority(self, error):
        return (np.abs(error) + self.e) ** self.a

    def add(self, error, sample):
        p = self._get_priority(error)
        self.tree.add(p, sample)

    def sample(self, n):
        batch = []
        idxs = []
        segment = self.tree.total() / n
        priorities = []

        self.beta = np.min([1., self.beta + self.beta_increment_per_sampling])

        for i in range(n):
            a = segment * i
            b = segment * (i + 1)

            s = random.uniform(a, b)
            (idx, p, data) = self.tree.get(s)
            priorities.append(p)
            batch.append(data)
            idxs.append(idx)

        sampling_probabilities = priorities / self.tree.total()
        is_weight = np.power(self.tree.n_entries * sampling_probabilities, -self.beta)
        is_weight /= is_weight.max()

        return batch, idxs, is_weight

    def update(self, idx, error):
        p = self._get_priority(error)
        self.tree.update(idx, p)

class SumTree:
    write = 0

    def __init__(self, capacity):
        self.capacity = capacity
        self.tree = np.zeros(2 * capacity - 1)
        self.data = np.zeros(capacity, dtype=object)
        self.n_entries = 0

    # update to the root node
    def _propagate(self, idx, change):
        parent = (idx - 1) // 2

        self.tree[parent] += change

        if parent != 0:
            self._propagate(parent, change)

    # find sample on leaf node
    def _retrieve(self, idx, s):
        left = 2 * idx + 1
        right = left + 1

        if left >= len(self.tree):
            return idx

        if s <= self.tree[left]:
            return self._retrieve(left, s)
        else:
            return self._retrieve(right, s - self.tree[left])

    def total(self):
        return self.tree[0]

    # store priority and sample
    def add(self, p, data):
        idx = self.write + self.capacity - 1

        self.data[self.write] = data
        self.update(idx, p)

        self.write += 1
        if self.write >= self.capacity:
            self.write = 0

        if self.n_entries < self.capacity:
            self.n_entries += 1

    # update priority
    def update(self, idx, p):
        change = p - self.tree[idx]

        self.tree[idx] = p
        self._propagate(idx, change)

    # get priority and sample
    def get(self, s):
        idx = self._retrieve(0, s)
        dataIdx = idx - self.capacity + 1

        return (idx, self.tree[idx], self.data[dataIdx])

class DeepQNetwork(nn.Module):
    def __init__(self, lr, n_actions, input_dims, n_neurons_layer = 512, dropout = 0.1, device ="cpu"):
        super(DeepQNetwork, self).__init__()

        self.fc1 = nn.Linear(input_dims, n_neurons_layer)
        self.fc2 = nn.Linear(n_neurons_layer, n_neurons_layer)
        self.fc3 = nn.Linear(n_neurons_layer, n_neurons_layer)
        self.fc4 = nn.Linear(n_neurons_layer, n_neurons_layer)
        self.fc5 = nn.Linear(n_neurons_layer, n_actions)

        # Definition of some Batch Normalization layers
        # self.bn1 = nn.BatchNorm1d(numberOfNeurons)
        # self.bn2 = nn.BatchNorm1d(numberOfNeurons)
        # self.bn3 = nn.BatchNorm1d(numberOfNeurons)
        # self.bn4 = nn.BatchNorm1d(numberOfNeurons)

        # Definition of some Dropout layers.
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)
        self.dropout3 = nn.Dropout(dropout)
        self.dropout4 = nn.Dropout(dropout)

        # Xavier initialization for the entire neural network
        nn.init.xavier_uniform_(self.fc1.weight)
        nn.init.xavier_uniform_(self.fc2.weight)
        nn.init.xavier_uniform_(self.fc3.weight)
        nn.init.xavier_uniform_(self.fc4.weight)
        nn.init.xavier_uniform_(self.fc5.weight)

        self.optimizer = optim.Adam(self.parameters(), lr=lr)

        self.loss = nn.MSELoss()
        self.device = device
        self.to(self.device)

    def forward(self, state):
        # x = self.dropout1(F.leaky_relu(self.bn1(self.fc1(state))))
        # x = self.dropout2(F.leaky_relu(self.bn2(self.fc2(x))))
        # x = self.dropout3(F.leaky_relu(self.bn3(self.fc3(x))))
        # x = self.dropout4(F.leaky_relu(self.bn4(self.fc4(x))))

        x = self.dropout1(F.leaky_relu(self.fc1(state)))
        x = self.dropout2(F.leaky_relu(self.fc2(x)))
        x = self.dropout3(F.leaky_relu(self.fc3(x)))
        x = self.dropout4(F.leaky_relu(self.fc4(x)))

        #x = F.leaky_relu(self.fc1(state))
        #x = F.leaky_relu(self.fc2(x))
        #x = F.leaky_relu(self.fc3(x))
        #x = F.leaky_relu(self.fc4(x))

        action = self.fc5(x)

        return action

    def save_checkpoint(self, path):
        T.save(self.state_dict(), path)

    def load_checkpoint(self, path):
        self.load_state_dict(T.load(path))


class DDQNAgent(object):
    def __init__(self, gamma, epsilon, lr, n_actions, input_dims,
                 mem_size, batch_size, id_agent,id_train_env,id_obs_type, eps_min=0.01, eps_dec=5e-7,
                 replace=1000, chkpt_dir='tmp/dqn', seed=1, device = "cpu", n_neurons_layer=512, dropout=0.1):
        self.gamma = gamma
        self.epsilon = epsilon
        self.lr = lr
        self.n_actions = n_actions
        self.input_dims = input_dims
        self.batch_size = batch_size
        self.eps_min = eps_min
        self.eps_dec = eps_dec
        self.replace_target_cnt = replace
        self.chkpt_dir = chkpt_dir
        self.action_space = [i for i in range(n_actions)]
        self.learn_step_counter = 0
        self.seed = seed
        self.writer = SummaryWriter(f"Tensorboard plot/DDQN/{id_agent}/{id_train_env}/{id_obs_type}")

        self.memory = Memory(mem_size)

        self.q_eval = DeepQNetwork(self.lr,
                                    self.n_actions,
                                    input_dims=self.input_dims,
                                    device=device,
                                    n_neurons_layer=n_neurons_layer,
                                    dropout=dropout)

        self.q_next = DeepQNetwork(self.lr,
                                    self.n_actions,
                                    input_dims=self.input_dims,
                                    device=device,
                                    n_neurons_layer=n_neurons_layer,
                                    dropout=dropout)

    def store_transition(self, state, action, reward, next_state, done):

        target = self.q_eval(Variable(T.FloatTensor(state).to(self.q_eval.device))).data
        target_val = self.q_next(Variable(T.FloatTensor(next_state).to(self.q_eval.device))).data
        target_eval = self.q_eval(Variable(T.FloatTensor(next_state).to(self.q_eval.device))).data

        old_val = target[action]
        next_val = 0
        if done:
            next_val = reward
        else:
            next_val = reward + self.gamma * T.max(target_val)

        error = abs(old_val -next_val).cpu().numpy()

        self.memory.add(error, (state, action, reward, next_state, done))

    def sample_memory(self):
        state, action, reward, new_state, done = \
            self.memory.sample_buffer(self.batch_size)

        states = T.tensor(state).to(self.q_eval.device)
        rewards = T.tensor(reward).to(self.q_eval.device)
        dones = T.tensor(done).to(self.q_eval.device)
        actions = T.tensor(action).to(self.q_eval.device)
        states_ = T.tensor(new_state).to(self.q_eval.device)

        return states, actions, rewards, states_, dones

    def choose_action(self, observation):
        if np.random.random() > self.epsilon:
            state = T.tensor([observation], dtype=T.float).to(self.q_eval.device)
            actions = self.q_eval.forward(state)
            action = T.argmax(actions).item()
        else:
            action = np.random.choice(self.action_space)

        return action

    def replace_target_network(self):
        if self.replace_target_cnt is not None and \
                self.learn_step_counter % self.replace_target_cnt == 0:
            self.q_next.load_state_dict(self.q_eval.state_dict())

    def decrement_epsilon(self):
        self.epsilon = self.epsilon - self.eps_dec \
            if self.epsilon > self.eps_min else self.eps_min

    def calculate_TD_error(self, state, action, reward, state_, terminal):

        # self.q_eval.optimizer.zero_grad()
        state = T.tensor(state).to(self.q_eval.device).float()
        # print(state.dtype)
        state_ = T.tensor(state_).to(self.q_eval.device).float()
        reward = T.tensor(reward).to(self.q_eval.device).float()
        q_pred = self.q_eval.forward(state)[action]

        q_next = self.q_next.forward(state_)
        q_next_max = q_next.max()
        # print(q_next,q_next_max)
        # input()
        if terminal:
            q_target = reward
        else:
            q_target = reward + self.gamma * q_next_max
        # print(type(q_target),type(q_pred))
        # input()
        error = self.q_eval.loss(q_target, q_pred).to(self.q_eval.device)
        return error

    def learn(self):
        if self.memory.tree.n_entries < self.batch_size:
            return

        self.q_eval.optimizer.zero_grad()
        self.replace_target_network()

        mini_batch, idxs, is_weights = self.memory.sample(self.batch_size)
        #???
        mini_batch = np.array(mini_batch).transpose()
        #???
        np_states =  np.array([e for e in mini_batch[0]],dtype=np.float32)
        np_actions = np.array([e for e in mini_batch[1]],dtype=np.int64)
        np_rewards = np.array([e for e in mini_batch[2]],dtype=np.float32)
        np_new_states = np.array([e for e in mini_batch[3]],dtype=np.float32)
        np_terminals = np.array([e for e in mini_batch[4]],dtype=np.bool)

        states = T.from_numpy(np_states).to(self.q_eval.device)
        actions = T.from_numpy(np_actions).to(self.q_eval.device)
        rewards = T.from_numpy(np_rewards).to(self.q_eval.device)
        states_ = T.from_numpy(np_new_states).to(self.q_eval.device)
        dones = T.from_numpy(np_terminals).to(self.q_eval.device)

        indices = np.arange(self.batch_size)

        q_pred = self.q_eval.forward(states)[indices, actions]
        q_next = self.q_next.forward(states_)
        q_eval = self.q_eval.forward(states_)

        max_actions = T.argmax(q_eval, dim=1)
        q_next[dones] = 0.0

        q_target = rewards + self.gamma * q_next[indices, max_actions]

        errors = T.abs(q_pred - q_target).data.cpu().numpy()

        # update priority
        for i in range(self.batch_size):
            idx = idxs[i]
            self.memory.update(idx, errors[i])

        loss = self.q_eval.loss(q_target, q_pred).to(self.q_eval.device)
        loss.backward()

        self.q_eval.optimizer.step()
        self.learn_step_counter += 1

        self.decrement_epsilon()
        return loss.item()

    def save_models(self, episode):
        self.q_eval.save_checkpoint(self.chkpt_dir + f"/episode{episode}/q_eval")
        self.q_next.save_checkpoint(self.chkpt_dir + f"/episode{episode}/q_next")

    def load_models(self, episode):
        self.q_eval.load_checkpoint(self.chkpt_dir + f"/episode{episode}/q_eval")
        self.q_next.load_checkpoint(self.chkpt_dir + f"/episode{episode}/q_next")

    def convert_obs(self, obs, obs_size):
        return obs.reshape(obs_size, )

    def train(self, env, coin, n_episodes=100, checkpoint_freq=10):
        best_score = -np.inf
        load_checkpoint = False

        n_steps = 0
        scores, eps_history, steps_array = [], [], []
        obs_size = self.input_dims
        for i in range(n_episodes):

            done = False
            observation = env.reset()
            observation = self.convert_obs(observation, obs_size)
            steps = 0
            score = 0
            loss = 0
            while not done:
                action = self.choose_action(observation)
                observation_, reward, done, info = env.step(action)
                observation_ = self.convert_obs(observation_, obs_size)
                score += reward

                # error = self.calculate_TD_error(observation,action,reward,observation_,done)
                error = reward
                self.store_transition(observation, action, reward, observation_, done)
                #self.store_transition(observation, action, reward, observation_, done)

                iteration_loss = self.learn()

                if iteration_loss != None:
                    loss += iteration_loss

                observation = observation_
                n_steps += 1
                steps += 1



            scores.append(score)
            steps_array.append(n_steps)

            self.writer.add_scalar(f"Train/Loss/{coin}", loss, i)
            self.writer.add_scalar(f"Train/Reward/{coin}", score, i)

            avg_scores = np.average(scores)
            print('episode: ', i, 'score: ', score, ' average score %.1f' % avg_scores, 'best score %.2f' % best_score,
                  'epsilon %.2f' % self.epsilon, 'steps', n_steps)

            eps_history.append(self.epsilon)

            if i % checkpoint_freq == 0:
                #path = os.getcwd()
                #dir = f"{path}/trained_agents/DDQNAgent/BTC/episode{i}"
                if os.path.exists(self.chkpt_dir + f"/episode{i}"):
                    shutil.rmtree(self.chkpt_dir + f"/episode{i}")
                os.makedirs(self.chkpt_dir + f"/episode{i}")
                self.save_models(i)
        return env

    def evaluate(self, env, coin, episode, env_id=None):

        self.epsilon = 0
        obs_size = self.input_dims
        self.q_eval.eval()
        done = False
        observation = env.reset()
        observation = self.convert_obs(observation, obs_size)

        while not done:
            action = self.choose_action(observation)
            observation_, reward, done, info = env.step(action)
            observation_ = self.convert_obs(observation_, obs_size)
            observation = observation_

        sharpe_ratio = env.sharpe_calculator_total_quantstats()
        sortino_ratio = env.sortino_calculator_total_quantstats()
        total_profit = list(env.returns_balance.values())[-1] - 10000
        total_reward = env._total_reward

        if env_id:
            tensorboard_path = f"Eval/{env_id}"
        else:
            tensorboard_path = "Eval"

        self.writer.add_scalar(f"{tensorboard_path}/Profit/{coin}", total_profit, episode)
        self.writer.add_scalar(f"{tensorboard_path}/Reward/{coin}", total_reward, episode)
        self.writer.add_scalar(f"{tensorboard_path}/Sharpe/{coin}", sharpe_ratio, episode)
        self.writer.add_scalar(f"{tensorboard_path}/Sortino/{coin}", sortino_ratio, episode)


        return env

# chkpt_dir = os.getcwd() + "/trained_agents/DDQN/BTC"
# env = gym.make(id_str, df=df, frame_bound=(122,326), window_size=22)

# obs_size = env.observation_space.shape[0] * env.observation_space.shape[1]
# agent =DDQNAgent(gamma=0.99,
#                 epsilon=1.0,
#                 lr=0.0001,
#                 input_dims=(obs_size),
#                 n_actions=env.action_space.n,
#                 mem_size=50000,
#                 eps_min=0.1,
#                 batch_size=32,
#                 replace=10000,
#                 eps_dec=1e-5,
#                 chkpt_dir=chkpt_dir,
#                 seed = 1,
#                 device = device
#                 )

# agent.train(env)
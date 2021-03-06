
import pandas as pd
from agents.Dqn_agent import DQNAgent
from agents.DDqn_agent import DDQNAgent
from agents.Duelling_DDqn_agent import DuelingDDQNAgent
from agents.DRQN_agent import DRQNAgent
import os
import torch
from env.ShortLongCTE_no_invalid import CryptoTradingEnv
import gym

# Register enviroment
id_str = 'cryptostocks-v1'

if 'cryptostocks-v1' in list(gym.envs.registry.env_specs.keys()):
  del gym.envs.registry.env_specs['cryptostocks-v1']

from gym.envs.registration import register
register(
    id=id_str,
    entry_point=CryptoTradingEnv,
)


def load_data(coin):
    # Load data
    path = os.getcwd()
    df = pd.read_csv(f"{path}\\data\\Binance_{coin}USDT_minute.csv", skiprows=1)
    df = df.rename(columns={'Volume USDT': 'volume'})
    df = df.iloc[::-1]
    df = df.drop(columns=['symbol', f"Volume {coin}"])
    df['date'] = pd.to_datetime(df['unix'], unit='ms')
    df = df.set_index("date")
    df = df.drop(columns=['unix'])
    return df


def eval_all(coin, pump_frame, dump_frame, id_agent):
    data = load_data(coin)
    env = gym.make(id_str, df=data, frame_bound=pump_frame, window_size=22, reward_option="profit")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    chkpt_dir = os.getcwd() + f"/trained_agents/DuelingDDQNAgent/{id_agent}/{coin}"
    save_fig_path = os.getcwd() + f"/plot/DuelingDDQNAgent/{id_agent}/{coin}"

    save_fig_path_pump = save_fig_path + "/pump"
    save_fig_path_dump = save_fig_path + "/dump"

    if not os.path.exists(save_fig_path_pump):
        os.makedirs(save_fig_path_pump)

    if not os.path.exists(save_fig_path_dump):
        os.makedirs(save_fig_path_dump)

    print("PUMP")
    obs_size = env.observation_space.shape[0] * env.observation_space.shape[1]
    agent = DuelingDDQNAgent(gamma=0.99,
                             epsilon=1.0,
                             lr=0.0001,
                             input_dims=(obs_size),
                             n_actions=env.action_space.n,
                             mem_size=50000,
                             eps_min=0.1,
                             batch_size=32,
                             replace=10000,
                             eps_dec=1e-5,
                             chkpt_dir=chkpt_dir,
                             seed=1,
                             device=device,
                             n_neurons_layer=512,
                             dropout=0.1,
                             id_agent = id_agent
                             )

    for i in range(10, 100, 10):
        agent.load_models(i)
        agent.evaluate(env,coin,i).render_all(i,savepath = save_fig_path_pump)

    print("DUMP")
    env = gym.make(id_str, df=data, frame_bound=dump_frame, window_size=22, reward_option="profit")

    obs_size = env.observation_space.shape[0] * env.observation_space.shape[1]
    agent = DuelingDDQNAgent(gamma=0.99,
                             epsilon=1.0,
                             lr=0.0001,
                             input_dims=(obs_size),
                             n_actions=env.action_space.n,
                             mem_size=50000,
                             eps_min=0.1,
                             batch_size=32,
                             replace=10000,
                             eps_dec=1e-5,
                             chkpt_dir=chkpt_dir,
                             seed=1,
                             device=device,
                             n_neurons_layer=512,
                             dropout=0.1
                             )

    for i in range(10, 100, 10):
        agent.load_models(i)
        agent.evaluate(env,coin,i).render_all(i, savepath = save_fig_path_dump)


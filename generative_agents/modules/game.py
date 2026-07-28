"""generative_agents.game"""

import os
import copy

from modules.utils import GenerativeAgentsMap, GenerativeAgentsKey
from modules import utils
from .maze import Maze
from .agent import Agent
from .magic_mirror import (
    DEFAULT_MANUAL_DAILY_SCHEDULE,
    GAME_DAY_MINUTES,
    MagicMirrorService,
)


class Game:
    """The Game"""

    def __init__(self, name, static_root, config, conversation, logger=None):
        self.name = name
        self.static_root = static_root
        self.record_iterval = config.get("record_iterval", 30)
        self.logger = logger or utils.IOLogger()
        self.maze = Maze(self.load_static(config["maze"]["path"]), self.logger)
        self.conversation = conversation
        self.agents = {}
        if "agent_base" in config:
            agent_base = config["agent_base"]
        else:
            agent_base = {}
        werewolf_config = config.setdefault("werewolf_game", {})
        if werewolf_config.get("enabled", True):
            werewolf_config.setdefault("game_day_minutes", GAME_DAY_MINUTES)
            werewolf_config.setdefault(
                "logical_day_start",
                utils.get_timer().get_date("%Y%m%d-%H:%M:%S"),
            )
            werewolf_config.setdefault(
                "manual_daily_schedule", DEFAULT_MANUAL_DAILY_SCHEDULE
            )
        storage_root = os.path.join(f"results/checkpoints/{name}", "storage")
        if not os.path.isdir(storage_root):
            os.makedirs(storage_root)
        for agent_name, agent in config["agents"].items():
            agent_config = utils.update_dict(
                copy.deepcopy(agent_base), self.load_static(agent["config_path"])
            )
            agent_config = utils.update_dict(agent_config, agent)
            if werewolf_config.get("enabled", True):
                schedule_config = agent_config.setdefault("schedule", {})
                schedule_config.setdefault("mode", "manual")
                schedule_config.setdefault(
                    "cycle_minutes", werewolf_config["game_day_minutes"]
                )
                schedule_config.setdefault(
                    "cycle_start", werewolf_config["logical_day_start"]
                )
                schedule_config.setdefault(
                    "manual_daily_schedule",
                    werewolf_config["manual_daily_schedule"],
                )

            agent_config["storage_root"] = os.path.join(storage_root, agent_name)
            self.agents[agent_name] = Agent(agent_config, self.maze, self.conversation, self.logger)
        self.magic_mirror = MagicMirrorService(
            self.name,
            werewolf_config,
            self.agents.keys(),
            logger=self.logger,
        )

    def get_agent(self, name):
        return self.agents[name]

    def agent_think(self, name, status):
        agent = self.get_agent(name)
        agent.set_werewolf_context(self.magic_mirror.context_for(name))
        plan = agent.think(status, self.agents)
        self._handle_werewolf_text_action(agent)
        self._collect_wolf_kill_votes_if_ready()
        if self.magic_mirror.should_collect_choice(agent.werewolf_context):
            target = agent.choose_werewolf_target()
            if self.magic_mirror.record_choice(name, agent.werewolf_context, target):
                self.logger.info("{} 向魔镜提交选择：{}".format(name, target))
            self.magic_mirror.resolve_if_ready()
        info = {
            "currently": agent.scratch.currently,
            "associate": agent.associate.abstract(),
            "concepts": {c.node_id: c.abstract() for c in agent.concepts},
            "chats": [
                {"name": "self" if n == agent.name else n, "chat": c}
                for n, c in agent.chats
            ],
            "action": agent.action.abstract(),
            "schedule": agent.schedule.abstract(),
            "address": agent.get_tile().get_address(as_list=False),
        }
        if (
            utils.get_timer().daily_duration() - agent.last_record
        ) > self.record_iterval:
            info["record"] = True
            agent.last_record = utils.get_timer().daily_duration()
        else:
            info["record"] = False
        if agent.llm_available():
            info["llm"] = agent._llm.get_summary()
        title = "{}.summary @ {}".format(
            name, utils.get_timer().get_date("%Y%m%d-%H:%M:%S")
        )
        self.logger.info("\n{}\n{}\n".format(utils.split_line(title), agent))
        return {"plan": plan, "info": info}

    def _append_conversation(self, speaker, listener, address, chats):
        key = utils.get_timer().get_date("%Y%m%d-%H:%M")
        if key not in self.conversation:
            self.conversation[key] = []
        if isinstance(address, (list, tuple)):
            address_text = "，".join(address)
        else:
            address_text = str(address)
        self.conversation[key].append(
            {"{} -> {} @ {}".format(speaker, listener, address_text): chats}
        )

    def _handle_werewolf_text_action(self, agent):
        context = agent.werewolf_context or {}
        required_action = context.get("required_action")
        if required_action == "give_morning_speech":
            if self.magic_mirror.has_morning_speech(agent.name, context):
                return
            text = agent.generate_morning_speech()
            if self.magic_mirror.record_morning_speech(agent.name, context, text):
                self._append_conversation(
                    agent.name,
                    "全体玩家",
                    ["the Ville", "会议区", "发言台"],
                    [(agent.name, text)],
                )
                self.logger.info("{} 正式发言：{}".format(agent.name, text))
            return

        if required_action == "discuss_werewolf_kill":
            if self.magic_mirror.has_wolf_discussion(agent.name, context):
                return
            discussion = agent.discuss_werewolf_kill()
            if self.magic_mirror.record_wolf_discussion(
                agent.name, context, discussion
            ):
                record = self.magic_mirror.config["wolf_discussions"][
                    context.get("phase_action_key") or self.magic_mirror.phase_action_key()
                ][agent.name]
                self._append_conversation(
                    agent.name,
                    "狼人同伴",
                    ["the Ville", "会议区", "椅子"],
                    [(agent.name, record["message"])],
                )
                self.logger.info(
                    "{} 狼人会议建议击杀 {}：{}".format(
                        agent.name, record["target"], record["message"]
                    )
                )

    def _collect_wolf_kill_votes_if_ready(self):
        if self.magic_mirror.config.get("phase") != "night_action":
            return
        if self.magic_mirror._night_stage()[0] != "wolf":
            return
        phase_key = self.magic_mirror.phase_action_key()
        if not self.magic_mirror.wolf_discussions_ready(phase_key):
            return
        for wolf_name in self.magic_mirror.alive_wolves():
            wolf = self.agents.get(wolf_name)
            if not wolf:
                continue
            context = self.magic_mirror.context_for(wolf_name)
            if context.get("required_action") != "choose_werewolf_kill_target":
                continue
            if not self.magic_mirror.should_collect_choice(context):
                continue
            wolf.set_werewolf_context(context)
            target = wolf.choose_werewolf_target()
            if self.magic_mirror.record_choice(wolf_name, context, target):
                self.logger.info("{} 向魔镜提交狼人击杀选择：{}".format(wolf_name, target))
        self.magic_mirror.resolve_if_ready()

    def load_static(self, path):
        return utils.load_dict(os.path.join(self.static_root, path))

    def reset_game(self):
        for a_name, agent in self.agents.items():
            agent.reset()
            title = "{}.reset".format(a_name)
            self.logger.info("\n{}\n{}\n".format(utils.split_line(title), agent))

    def restart_werewolf_game_if_finished(self):
        if not self.magic_mirror.config.get("auto_restart_on_win", True):
            return None

        previous_game = self.magic_mirror.restart_finished_game()
        if not previous_game:
            return None

        for agent in self.agents.values():
            agent.set_werewolf_context({})
        return previous_game


def create_game(name, static_root, config, conversation, logger=None):
    """Create the game"""

    utils.set_timer(**config.get("time", {}))
    GenerativeAgentsMap.set(GenerativeAgentsKey.GAME, Game(name, static_root, config, conversation, logger=logger))
    return GenerativeAgentsMap.get(GenerativeAgentsKey.GAME)


def get_game():
    """Get the gloabl game"""

    return GenerativeAgentsMap.get(GenerativeAgentsKey.GAME)

"""Structured recorder for werewolf game reports."""

import copy
import json
import os

from modules import utils


SCHEMA_VERSION = 1


class WerewolfGameRecorder:
    """Write one detailed report file for each werewolf game."""

    def __init__(self, simulation_name, player_names):
        self.simulation_name = simulation_name
        self.player_names = list(player_names)
        self.records_root = os.path.join(
            "results", "checkpoints", simulation_name, "werewolf_records"
        )
        self.index_path = os.path.join(self.records_root, "index.json")

    def start_game(self, config):
        game = self._load_game(config)
        game["started_at"] = game.get("started_at") or self._now()
        game["settings"] = self._settings(config)
        game["roles"] = self._roles(config)
        game["final_state"] = self._state(config)
        self._save_game(game)
        return game

    def close_game(self, config):
        game = self._load_game(config)
        game["ended_at"] = game.get("ended_at") or self._now()
        game["winner"] = config.get("winner")
        game["winner_reason"] = config.get("winner_reason", "")
        game["settings"] = self._settings(config)
        game["roles"] = self._roles(config)
        game["final_state"] = self._state(config)
        has_game_over_event = any(
            event.get("event_type") == "game_over"
            and event.get("data", {}).get("winner") == config.get("winner")
            for event in game.get("events", [])
        )
        if not has_game_over_event:
            self._append_event(
                game,
                config,
                "game_over",
                "游戏结束。获胜阵营为：{}。".format(config.get("winner")),
                {
                    "winner": config.get("winner"),
                    "winner_reason": config.get("winner_reason", ""),
                    "final_state": game["final_state"],
                },
            )
        self._save_game(game)
        return game

    def record_public_message(self, config, entry):
        game = self._load_game(config)
        game["settings"] = self._settings(config)
        game["roles"] = self._roles(config)
        self._append_event(
            game,
            config,
            entry.get("event_type", "public_message"),
            entry.get("message", ""),
            {
                "speaker": entry.get("speaker"),
                "message": entry.get("message"),
                "public_info": entry.get("public_info", {}),
            },
        )
        self._save_game(game)

    def record_role_assignment(self, config):
        game = self._load_game(config)
        game["settings"] = self._settings(config)
        game["roles"] = self._roles(config)
        self._append_event(
            game,
            config,
            "roles_assigned",
            "身份牌已经发放。",
            {"roles": game["roles"]},
        )
        self._save_game(game)

    def record_speech_preference(self, config, phase_key, actor, record, candidates):
        game = self._load_game(config)
        round_data = self._ensure_round(game, config)
        preferences = round_data.setdefault("speech_preferences", {}).setdefault(
            phase_key, {}
        )
        preferences[actor] = {
            "time": record.get("time"),
            "role": record.get("role"),
            "choice": record.get("preference"),
            "candidates": list(candidates),
        }
        self._append_event(
            game,
            config,
            "speech_preference_recorded",
            "{}申报发言意愿：{}。".format(actor, record.get("preference")),
            {
                "phase_key": phase_key,
                "actor": actor,
                "choice": record.get("preference"),
                "candidates": list(candidates),
            },
        )
        self._save_game(game)

    def record_speech_order_vote(self, config, phase_key, actor, record, candidates):
        game = self._load_game(config)
        round_data = self._ensure_round(game, config)
        votes = round_data.setdefault("speech_order_votes", {}).setdefault(
            phase_key, {}
        )
        votes[actor] = {
            "time": record.get("time"),
            "role": record.get("role"),
            "submitted_order": list(record.get("order", [])),
            "candidates": list(candidates),
        }
        self._append_event(
            game,
            config,
            "speech_order_vote_recorded",
            "{}提交发言顺序投票。".format(actor),
            {
                "phase_key": phase_key,
                "actor": actor,
                "submitted_order": list(record.get("order", [])),
                "candidates": list(candidates),
            },
        )
        self._save_game(game)

    def record_speech_preferences_resolved(self, config, phase_key, preferences):
        game = self._load_game(config)
        round_data = self._ensure_round(game, config)
        round_data.setdefault("speech_preferences", {})[phase_key] = copy.deepcopy(
            preferences
        )
        self._append_event(
            game,
            config,
            "speech_preferences_resolved",
            "发言意愿申报结束。",
            {
                "phase_key": phase_key,
                "preferences": copy.deepcopy(preferences),
            },
        )
        self._save_game(game)

    def record_speech_order_resolved(
        self, config, phase_key, order, scores, votes, preferences
    ):
        game = self._load_game(config)
        round_data = self._ensure_round(game, config)
        results = round_data.setdefault("speech_order_results", {})
        results[phase_key] = {
            "time": self._now(),
            "final_order": list(order),
            "scores": copy.deepcopy(scores),
            "votes": copy.deepcopy(votes),
            "preferences": copy.deepcopy(preferences),
        }
        round_data["final_speech_order"] = list(order)
        self._append_event(
            game,
            config,
            "speech_order_resolved",
            "正式发言顺序已确定。",
            {
                "phase_key": phase_key,
                "final_order": list(order),
                "scores": copy.deepcopy(scores),
            },
        )
        self._save_game(game)

    def record_morning_speech(self, config, phase_key, speaker, text):
        game = self._load_game(config)
        round_data = self._ensure_round(game, config)
        speeches = round_data.setdefault("formal_speeches", {}).setdefault(
            phase_key, {}
        )
        speeches[speaker] = {
            "time": self._now(),
            "role": config.get("players", {}).get(speaker, {}).get("role"),
            "text": text,
        }
        self._append_event(
            game,
            config,
            "morning_speech_recorded",
            "{}完成正式发言。".format(speaker),
            {
                "phase_key": phase_key,
                "speaker": speaker,
                "text": text,
            },
        )
        self._save_game(game)

    def record_wolf_discussion(self, config, phase_key, actor, record, candidates):
        game = self._load_game(config)
        round_data = self._ensure_round(game, config)
        discussions = round_data.setdefault("wolf_discussions", {}).setdefault(
            phase_key, {}
        )
        discussions[actor] = {
            "time": record.get("time"),
            "role": record.get("role"),
            "target": record.get("target"),
            "message": record.get("message"),
            "candidates": list(candidates),
        }
        self._append_event(
            game,
            config,
            "wolf_discussion_recorded",
            "{}提出狼人夜聊意见：{}。".format(actor, record.get("target")),
            {
                "phase_key": phase_key,
                "actor": actor,
                "target": record.get("target"),
                "message": record.get("message"),
                "candidates": list(candidates),
            },
        )
        self._save_game(game)

    def record_vote_choice(self, config, phase_key, actor, action, candidates, vote_order):
        game = self._load_game(config)
        round_data = self._ensure_round(game, config)
        vote_data = self._ensure_vote_data(round_data, phase_key, action, vote_order)
        vote_data.setdefault("choices", {})[actor] = {
            "time": action.get("time"),
            "role": action.get("role"),
            "target": action.get("target"),
            "candidates": list(candidates),
        }
        self._append_event(
            game,
            config,
            "vote_choice_recorded",
            "{}投票给{}。".format(actor, action.get("target")),
            {
                "phase_key": phase_key,
                "actor": actor,
                "target": action.get("target"),
                "candidates": list(candidates),
                "vote_order": list(vote_order),
            },
        )
        self._save_game(game)

    def record_vote_resolved(self, config, phase_key, actions, tally, exiled, vote_order):
        game = self._load_game(config)
        round_data = self._ensure_round(game, config)
        vote_data = self._ensure_vote_data(
            round_data,
            phase_key,
            {"phase": config.get("phase", "")},
            vote_order,
        )
        vote_data["choices"] = copy.deepcopy(actions)
        vote_data["tally"] = copy.deepcopy(tally)
        vote_data["exiled_player"] = exiled
        vote_data["resolved_at"] = self._now()
        self._append_event(
            game,
            config,
            "vote_resolved",
            "投票结算完成。被放逐玩家：{}。".format(exiled or "无"),
            {
                "phase_key": phase_key,
                "tally": copy.deepcopy(tally),
                "exiled_player": exiled,
                "vote_order": list(vote_order),
            },
        )
        self._save_game(game)

    def record_special_action(self, config, phase_key, actor, action, candidates):
        game = self._load_game(config)
        round_data = self._ensure_round(game, config)
        action_data = self._ensure_special_action_data(round_data, phase_key)
        action_data.setdefault("actions", {})[actor] = {
            "time": action.get("time"),
            "role": action.get("role"),
            "required_action": action.get("required_action"),
            "target": action.get("target"),
            "candidates": list(candidates),
        }
        self._append_event(
            game,
            config,
            "special_action_recorded",
            "{}提交特殊行动：{}。".format(actor, action.get("target")),
            {
                "phase_key": phase_key,
                "actor": actor,
                "role": action.get("role"),
                "required_action": action.get("required_action"),
                "target": action.get("target"),
                "candidates": list(candidates),
            },
        )
        self._save_game(game)

    def record_special_result(self, config, phase_key, result_type, data):
        game = self._load_game(config)
        round_data = self._ensure_round(game, config)
        action_data = self._ensure_special_action_data(round_data, phase_key)
        action_data.setdefault("results", []).append(
            {
                "time": self._now(),
                "type": result_type,
                "data": copy.deepcopy(data),
            }
        )
        self._append_event(
            game,
            config,
            result_type,
            "{}结算完成。".format(result_type),
            {"phase_key": phase_key, **copy.deepcopy(data)},
        )
        self._save_game(game)

    def record_death(self, config, name, reason, player):
        game = self._load_game(config)
        round_data = self._ensure_round(game, config)
        death = {
            "time": self._now(),
            "name": name,
            "reason": reason,
            "role": player.get("role"),
            "team": player.get("team"),
            "phase": config.get("phase", ""),
        }
        deaths = round_data.setdefault("deaths", [])
        if not any(
            item.get("name") == name and item.get("reason") == reason
            for item in deaths
        ):
            deaths.append(death)
        game["final_state"] = self._state(config)
        self._append_event(
            game,
            config,
            "player_died",
            "{}出局，原因：{}。".format(name, reason),
            death,
        )
        self._save_game(game)

    def update_round_state(self, config):
        game = self._load_game(config)
        round_data = self._ensure_round(game, config)
        round_data["end_state"] = self._state(config)
        game["final_state"] = round_data["end_state"]
        self._save_game(game)

    def _ensure_vote_data(self, round_data, phase_key, action, vote_order):
        votes = round_data.setdefault("votes", {})
        vote_data = votes.setdefault(
            phase_key,
            {
                "phase": action.get("phase", ""),
                "vote_order": list(vote_order),
                "choices": {},
                "tally": {},
                "exiled_player": None,
            },
        )
        vote_data["vote_order"] = list(vote_order)
        return vote_data

    def _ensure_special_action_data(self, round_data, phase_key):
        special_actions = round_data.setdefault("special_actions", {})
        return special_actions.setdefault(
            phase_key,
            {
                "phase": "night_action",
                "actions": {},
                "results": [],
            },
        )

    def _load_game(self, config):
        game_index = int(config.get("game_index", 1))
        path = self._game_path(game_index)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "schema_version": SCHEMA_VERSION,
            "simulation_name": self.simulation_name,
            "game_index": game_index,
            "file": self._game_file_name(game_index),
            "started_at": self._now(),
            "ended_at": None,
            "winner": None,
            "winner_reason": "",
            "settings": self._settings(config),
            "roles": self._roles(config),
            "rounds": [],
            "events": [],
            "final_state": self._state(config),
        }

    def _save_game(self, game):
        game["updated_at"] = self._now()
        self._atomic_write(self._game_path(game["game_index"]), game)
        self._update_index(game)

    def _update_index(self, game):
        index = self._load_index()
        summary = {
            "game_index": game["game_index"],
            "file": game["file"],
            "started_at": game.get("started_at"),
            "ended_at": game.get("ended_at"),
            "winner": game.get("winner"),
            "winner_reason": game.get("winner_reason", ""),
            "round_count": len(game.get("rounds", [])),
        }
        games = [
            item
            for item in index.get("games", [])
            if item.get("game_index") != game["game_index"]
        ]
        games.append(summary)
        games.sort(key=lambda item: item.get("game_index", 0))
        index["games"] = games
        index["updated_at"] = self._now()
        self._atomic_write(self.index_path, index)

    def _load_index(self):
        if os.path.exists(self.index_path):
            with open(self.index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "schema_version": SCHEMA_VERSION,
            "simulation_name": self.simulation_name,
            "updated_at": self._now(),
            "games": [],
        }

    def _ensure_round(self, game, config):
        round_no = int(config.get("round", 1))
        date_key = config.get("current_date") or utils.get_timer().get_date("%Y%m%d")
        for round_data in game.setdefault("rounds", []):
            if round_data.get("round") == round_no and round_data.get("date") == date_key:
                return round_data
        round_data = {
            "round": round_no,
            "date": date_key,
            "started_at": self._now(),
            "speech_preferences": {},
            "speech_order_votes": {},
            "speech_order_results": {},
            "final_speech_order": [],
            "formal_speeches": {},
            "wolf_discussions": {},
            "votes": {},
            "special_actions": {},
            "deaths": [],
            "end_state": self._state(config),
        }
        game["rounds"].append(round_data)
        game["rounds"].sort(key=lambda item: (item.get("round", 0), item.get("date", "")))
        return round_data

    def _append_event(self, game, config, event_type, summary, data):
        event = {
            "time": self._now(),
            "game_index": int(config.get("game_index", game.get("game_index", 1))),
            "round": int(config.get("round", 1)),
            "date": config.get("current_date") or utils.get_timer().get_date("%Y%m%d"),
            "phase": config.get("phase", ""),
            "phase_name": config.get("phase_name", ""),
            "event_type": event_type,
            "summary": summary,
            "data": data,
        }
        game.setdefault("events", []).append(event)

    def _settings(self, config):
        return {
            "seed": config.get("seed"),
            "skip_first_day_vote": config.get("skip_first_day_vote", True),
            "sequential_vote_slot_minutes": config.get(
                "sequential_vote_slot_minutes"
            ),
            "speech_preference_minutes": config.get("speech_preference_minutes"),
            "speech_order_vote_minutes": config.get("speech_order_vote_minutes"),
            "speech_slot_minutes": config.get("speech_slot_minutes"),
            "auto_restart_on_win": config.get("auto_restart_on_win", True),
            "role_assignment_mode": config.get("role_assignment_mode"),
            "role_assignment_source": config.get("role_assignment_source"),
            "role_assignment_plan_path": config.get("role_assignment_plan_path"),
            "role_assignment_plan_id": config.get("role_assignment_plan_id"),
            "role_assignment_plan_game": config.get("role_assignment_plan_game"),
            "max_games": config.get("max_games"),
            "stop_after_max_games": config.get("stop_after_max_games"),
        }

    def _roles(self, config):
        roles = {}
        for name, player in config.get("players", {}).items():
            if player.get("is_game_master"):
                continue
            roles[name] = {
                "role": player.get("role"),
                "team": player.get("team"),
            }
        return roles

    def _state(self, config):
        alive, dead = [], []
        for name, player in config.get("players", {}).items():
            if player.get("is_game_master"):
                continue
            if player.get("alive", True):
                alive.append(name)
            else:
                dead.append(name)
        return {
            "alive_players": alive,
            "dead_players": dead,
            "players": copy.deepcopy(config.get("players", {})),
        }

    def _game_file_name(self, game_index):
        return "game_{:04d}.json".format(int(game_index))

    def _game_path(self, game_index):
        return os.path.join(self.records_root, self._game_file_name(game_index))

    def _atomic_write(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = "{}.tmp".format(path)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)

    def _now(self):
        return utils.get_timer().get_date("%Y%m%d-%H:%M")

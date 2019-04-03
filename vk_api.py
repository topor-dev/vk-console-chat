# -*- coding: utf-8 -*-
import collections
import json
import sys
import time
from random import randint

import requests


class VK_api:
    def __init__(self, token, long_pool={}, logger=None):
        self.token = token
        self.logger = logger
        if long_pool and all((val != "" for val in long_pool.values())):
            self.long_pool_config = long_pool
        else:
            self.long_pool_config = self._get_long_pool_config()
            if not self.long_pool_config:
                print("exited, cant load long_pool config")
                raise SystemExit(-1)
            self.logged_add("long pool loaded successfully")

    def logged_add(self, msg):
        if self.logger:
            self.logger.add(msg)

    def _get_long_pool_str(self, config=None):
        if config is None:
            config = {}
        _long_pool_str = "https://{server}?act=a_check&"
        # key={key}
        # ts={ts}
        # mode={mode}
        # 'https://{server}?act=a_check&key={key}&ts={ts}&wait=25&mode={mode}'
        if not "mode" in config:
            config["mode"] = 1
        if not "wait" in config:
            config["wait"] = 25
        config.update(self.long_pool_config)

        if (
            "server" in config
            and "key" in config
            and "ts" in config
            and all((val != "" for val in config.values()))
        ):
            _long_pool_str = _long_pool_str.format(**config)
            del config["server"]
            return _long_pool_str + "&".join(
                ["%s=%s" % (k, v) for k, v in config.items()]
            )
        self.long_pool_config = self._get_long_pool_config()
        return self._get_long_pool_str(config)

    def _get_long_pool_config(self):
        # res = self.api_request('messages.getLongPollServer',{'need_pts':1,})
        res = self.api_request("messages.getLongPollServer", {"v": 5.4})
        if "error" in res:
            self.logged_add("error getLongPollServer: %s" % res["error"])
            time.sleep(0.5)
            return {}
        return res["response"]

    def api_request(self, method, params={}):
        time.sleep(0.5)  # ограничение
        return json.loads(
            self.request(
                "https://api.vk.com/method/%s?access_token=%s&%s"
                % (
                    method,
                    self.token,
                    "&".join(["%s=%s" % (k, v) for k, v in params.items()]),
                )
            )
        )

    def request(self, url, params={}):
        res = requests.get(url, **params)
        return res.content.decode("utf-8")

    def get_long_pool(self, config={}):
        """get_long_pool(config={})"""
        url = self._get_long_pool_str(config)
        res = {}
        timeout = 30
        if "timeout" in config:
            timeout = config["timeout"] + 5
        res_ = self.request(url, {"timeout": timeout})
        try:
            res = json.loads(res_)
        except ValueError:
            print("failed load this json:", res_, sep="\n", flush=True)
            res = {"failed": 2}  # let us reload
        # res = json.loads(self.request(url))
        if "failed" in res:
            self.logged_add("some fail with long pool server: %s" % res)
            if res["failed"] == 1:
                self.long_pool_config["ts"] = res["ts"]
            if res["failed"] == 2 or res["failed"] == 3:
                self.long_pool_config = self._get_long_pool_config()
            time.sleep(2)  # lets wait for 2 sec
            return self.get_long_pool()
        self.long_pool_config["ts"] = res["ts"]
        return res

    def message__send(self, peer_id: int, msg: str):
        res = self.api_request(
            "messages.send",
            {
                "peer_id": peer_id,
                "message": msg,
                "v": "5.53",
                "random_id": randint(0, 65535),
            },
        )
        if "error" in res:
            return (False, res["error"])
        return (True, res)

    def messages__send(self, peer_id_and_msg: list):
        resend = []
        for id, msg in peer_id_and_msg:
            success, res = self.message__send(id, msg)
            if not success:
                self.logged_add("some error while send message: %s" % res)
                resend.append((id, msg))
        if not resend:
            time.sleep(0.3)
            return (True, None)
        return (False, resend)

    def messages__mark_as_read(self, m_ids=[]):
        if not m_ids:
            return (True, {})
        to_mark = ",".join(map(str, m_ids))
        res = self.api_request(
            "messages.markAsRead", {"message_ids": to_mark, "v": "5.53"}
        )
        if "error" in res:
            self.logged_add("some error while mark message as read: %s" % res["error"])
            return (False, res["error"])
        return (True, res)

    def account_setOnline(self):
        res = self.api_request("account.setOnline", {"voip": "0", "v": "5.38"})
        if "error" in res:
            return (False, res["error"])
        return (True, res["response"])

    def messages__getLastActivity(self, user_id):
        res = self.api_request(
            "messages.getLastActivity", {"user_id": user_id, "v": "5.4"}
        )
        if "error" in res:
            return (False, res["error"])
        return (True, res["response"])

    def messages__getHistory(self, peer_id, count, rev=0):
        """
        rev: 1 - return in chronologic order, 0 - reverse
        """
        res = self.api_request(
            "messages.getHistory",
            {"peer_id": peer_id, "count": count, "rev": rev, "v": "5.52"},
        )
        if "error" in res:
            return (False, res["error"])
        return (True, res["response"])

    def users__get(self, user_ids=[]):
        if hasattr(user_ids, "__iter__") and not isinstance(user_ids, str):
            user_ids = ",".join(map(str, user_ids))
        else:
            user_ids = str(user_ids)
        res = self.api_request("users.get", {"user_ids": user_ids, "v": "5.52"})
        if "error" in res:
            return (False, res["error"])
        return (True, res["response"])

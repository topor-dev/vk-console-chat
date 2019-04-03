#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import html  # unescape
import itertools
import os
import sys  # sys.stdin.read, argv
from collections import deque
from datetime import datetime
from enum import Enum
from threading import Lock, Thread, current_thread
from time import sleep

import click  # edit

from vk_api import VK_api

MESSAGES_LIMIT = 10
ERRORS_LIMIT = 5

WATCH_ON = [1,2,3]  # list of id here

GLOBAL_VK = None

GLOBAL_ERRORS = deque(maxlen=ERRORS_LIMIT)


def log_error(e):
    GLOBAL_ERRORS.append((datetime.now().strftime("%H:%M:%S"), e))


class StateType(Enum):
    ALL_CHATS_PAGE = 1
    CHAT_PAGE = 2
    CHAT_WRITE_MESSAGE_PAGE = 3
    CHAT_SEND_MESSAGE_PAGE = 4


class EventType(Enum):
    MESSAGE = 4
    SET_ONLINE = 8
    SET_OFFLINE = 9


# https://stackoverflow.com/questions/30239092/how-to-get-multiline-input-from-user


class Status:
    messages = {}
    """
    {
        uid:{
            'm_id':_,
            'out':_,
            'timestamp':_,
            'title':_,
            'body':_,
            'read_state':_ ?
        }
    }
    """
    is_online = {}
    """
    {
        uid:{
            'status':_,
            'timestamp':_
        }
    }
    """
    users_write_mutex = Lock()
    users = deque(WATCH_ON, maxlen=10)  # TODO: add update dialog-list
    """
    [
        {
            id:id:_,
            first_name:_,
            last_name:_,
        }

        or

        id
    ]
    """


class State:
    state = StateType.ALL_CHATS_PAGE
    args = []
    multiline_input = False

    def __init__(self):
        self.rw_mutex = Lock()


GLOBAL_STATUS = Status()
GLOBAL_STATE = State()


def mark_as_deamon(class_):
    """mark thread as daemon"""

    def f(*args, **kwargs):
        t = class_(*args, **kwargs)
        t.daemon = True
        return t

    return f


def autorun(class_):
    """make thread run after call """

    def f(*args, **kwargs):
        t = class_(*args, **kwargs)
        t.start()
        return t

    return f


def run_in_other_thread(func):
    """make function running in other thread"""

    def f(*args, **kwargs):
        t = Thread(target=func, args=args, kwargs=kwargs)
        return t

    return f


class synchronize_with_lock:
    """
    Synchronize decorator
    if decorate with parameter (should be Lock-like object), lock execution function on it
    if decorate without parameters - create Lock object and lock on it (one lock object per function)
    """

    _locks = {}
    used_as_decorator = False

    def __init__(self, lock_or_func=None):
        if callable(lock_or_func):  # used as decorator, without arguments
            self.used_as_decorator = True
            self._locks[id(self)] = Lock()
            self.func = lock_or_func
        else:  # used as decorator-factory
            if not hasattr(lock_or_func, "__enter__") or not hasattr(
                lock_or_func, "__exit__"
            ):
                raise AttributeError(
                    "lock should have __enter__ and __exit__ attributes"
                )
            self._locks[id(self)] = lock_or_func
            # def decorator(f)
            pass

    def __call__(self, *args, **kwargs):
        lock = self._locks[id(self)]
        if self.used_as_decorator:
            with lock:
                return self.func(*args, **kwargs)
        # else - called as factory to create decorator
        orig_args = args

        def decorator(*args, **kwargs):
            with lock:
                return orig_args[0](*args, **kwargs)

        return decorator


def clear():
    click.clear()
    # print('\n'*10)
    pass


def update_users_info():
    to_update = {}
    with GLOBAL_STATUS.users_write_mutex:
        for ind, user_info in enumerate(list(GLOBAL_STATUS.users)):
            uid = None
            if isinstance(user_info, dict):
                if not "recheck" in user_info:
                    continue
                uid = user_info["id"]
            else:
                uid = user_info
            to_update[uid] = ind
        success, res = GLOBAL_VK.users__get(to_update)
        if not success:
            log_error(res)
            return
        for info in res:
            ind = to_update[info["id"]]
            GLOBAL_STATUS.users[ind] = info


def get_online_str(uid):
    return "[+]" if GLOBAL_STATUS.is_online[uid]["status"] else "[-]"
    pass


def get_name_by_id(id):
    for user_info in GLOBAL_STATUS.users:
        if isinstance(user_info, int):
            update_users_info()
            break
        if user_info["id"] == id:
            return user_info["first_name"] + " " + user_info["last_name"]
    for user_info in GLOBAL_STATUS.users:
        if user_info["id"] == id:
            return user_info["first_name"] + " " + user_info["last_name"]
    return str(id)


@synchronize_with_lock(GLOBAL_STATE.rw_mutex)
def draw_page(force=False):
    if GLOBAL_STATE.state in [StateType.CHAT_WRITE_MESSAGE_PAGE] and not force:
        return
    clear()
    print(*(v for v in GLOBAL_ERRORS), sep="\n")

    print("-" * 20)
    print(GLOBAL_STATE.state.name)
    print("-" * 20)
    {
        StateType.ALL_CHATS_PAGE: draw__ALL_CHATS_PAGE,
        StateType.CHAT_PAGE: draw__CHAT_PAGE,
        StateType.CHAT_WRITE_MESSAGE_PAGE: draw__CHAT_WRITE_MESSAGE_PAGE,
        StateType.CHAT_SEND_MESSAGE_PAGE: draw__CHAT_SEND_MESSAGE_PAGE,
    }.get(
        GLOBAL_STATE.state,
        lambda *args: print(
            "Not implemented, state:", GLOBAL_STATE.state, "args:", args
        ),
    )(
        *GLOBAL_STATE.args
    )


def draw__ALL_CHATS_PAGE(*args):
    update_users_info()
    for index, user_info in enumerate(GLOBAL_STATUS.users, 1):
        uid = user_info["id"]
        if not uid in GLOBAL_STATUS.is_online:
            update_user_online_status(uid)
            if not uid in GLOBAL_STATUS.messages:
                get_last_n_messages(uid)

        # TODO: add check if new messages exists
        print(
            index,
            "]",
            get_name_by_id(uid),
            datetime.fromtimestamp(GLOBAL_STATUS.is_online[uid]["timestamp"]).strftime(
                "%H:%M:%S"
            ),
            get_online_str(uid),
            end="\n" + "-" * 10 + "\n",
        )


@autorun
@mark_as_deamon
@run_in_other_thread
def mark_messages_as_read(messages):
    to_mark = []
    for msg in messages:
        if not msg["out"]:
            to_mark.append(msg["m_id"])
    log_error(("mark as read", to_mark))
    return
    success, res = GLOBAL_VK.messages__mark_as_read(to_mark)
    if not success:
        log_error(res)


def draw_part_chat(chat_id):
    for msg in GLOBAL_STATUS.messages[chat_id]:
        if "fwd" in msg:
            print("[fwd]", end="")
        print("<< " if msg["out"] else ">> ", msg["strftime"], end=" ")
        if "sticker" in msg:
            print("[sticker]", msg["sticker"])
        else:
            print(msg["body"])

        if "attachments" in msg:
            print(msg["attachments"])


def draw__CHAT_PAGE(chat_id=None, *args):
    if chat_id is None:
        return
    print(get_name_by_id(chat_id), get_online_str(chat_id))
    print("\n" * 2)
    draw_part_chat(chat_id)
    draw_part_menu(
        ["back", "write message"], 0
    )  # TODO: add option mark as read, if no read by default


def draw__CHAT_SEND_MESSAGE_PAGE(uid, msg, *args):
    print("-" * 6)
    print(
        "send",
        msg,
        "to user",
        get_name_by_id(uid),
        '?(y,yes,"" - for agree)',
        sep="\n" + "-" * 2 + "\n",
    )
    print("-" * 6)


def draw__CHAT_WRITE_MESSAGE_PAGE(uid, *args):
    print("message to user", get_name_by_id(uid))
    print("-" * 4)
    draw_part_chat(uid)
    print("-" * 4)
    print("ctrl+d to end write")
    print("-" * 4)


def draw_part_menu(options: list, iterable_or_start=1, extra=None):
    keys = None
    if isinstance(iterable_or_start, int):
        keys = itertools.count(iterable_or_start)
    else:  # iterable
        keys = iterable_or_start

    for key, option in zip(keys, options):
        print(key, "]", option)
    if extra:
        print(extra)


@synchronize_with_lock(GLOBAL_STATE.rw_mutex)
def user_input_handler(query):
    print("ask for:", query)

    if GLOBAL_STATE.state == StateType.ALL_CHATS_PAGE:
        if not query.isdigit():
            return False
        ind = int(query) - 1
        if ind >= len(GLOBAL_STATUS.users) or ind < 0:
            return False

        chat_id = GLOBAL_STATUS.users[ind]["id"]
        GLOBAL_STATE.args = [chat_id]
        GLOBAL_STATE.state = StateType.CHAT_PAGE
        mark_messages_as_read(GLOBAL_STATUS.messages[chat_id])
        return False
    if GLOBAL_STATE.state == StateType.CHAT_PAGE:
        if not query.isdigit():
            return False
        query = int(query)
        if query == 0:
            GLOBAL_STATE.args = []
            GLOBAL_STATE.state = StateType.ALL_CHATS_PAGE
            return False
        if query == 1:
            mark_messages_as_read(GLOBAL_STATUS.messages[GLOBAL_STATE.args[0]])
            GLOBAL_STATE.multiline_input = True
            GLOBAL_STATE.state = StateType.CHAT_WRITE_MESSAGE_PAGE
            return True
        return False
    if GLOBAL_STATE.state == StateType.CHAT_WRITE_MESSAGE_PAGE:
        GLOBAL_STATE.multiline_input = False
        if query == "":
            GLOBAL_STATE.state = StateType.CHAT_PAGE
            return False
        GLOBAL_STATE.args.append(query)
        GLOBAL_STATE.state = StateType.CHAT_SEND_MESSAGE_PAGE
        return False
    if GLOBAL_STATE.state == StateType.CHAT_SEND_MESSAGE_PAGE:
        if query in ["yes", "y", ""]:
            GLOBAL_VK.message__send(*GLOBAL_STATE.args)
        GLOBAL_STATE.args = GLOBAL_STATE.args[:1]
        GLOBAL_STATE.state = StateType.CHAT_PAGE
        return False
    return False


def update_user_online_status(user_id):
    success, res = GLOBAL_VK.messages__getLastActivity(user_id)
    if not success:
        log_error(res)

        GLOBAL_STATUS.is_online[user_id] = {"status": 0, "timestamp": 0}
        return

    GLOBAL_STATUS.is_online[user_id] = {
        "status": res["online"],
        "timestamp": res["time"],
    }


@autorun
@mark_as_deamon
@run_in_other_thread
def get_last_n_messages(user_id):
    success, res = GLOBAL_VK.messages__getHistory(user_id, MESSAGES_LIMIT)
    if not success:
        log_error(res)
        GLOBAL_STATUS.messages[user_id] = deque(maxlen=MESSAGES_LIMIT)
        return

    def _perfomr_message(e):
        res = {
            "m_id": e["id"],
            "out": e["out"],
            "timestamp": e["date"],
            "body": e["body"],
            "read_state": e["read_state"],
            "strftime": datetime.fromtimestamp(e["date"]).strftime(
                "%H:%M:%S"
            ),  # TODO: remove
        }
        if "fwd_messages" in e:
            res["fwd"] = True  # TODO: replace

        if "attachments" in e:
            res["attachments"] = []
            for attach in e["attachments"]:
                if attach["type"] == "sticker":
                    res["sticker"] = (attach["sticker"]["id"],)
                    return res  # only sticker and no one else can be in attach
                res["attachments"].append(attach["type"])
        return res

    GLOBAL_STATUS.messages[user_id] = deque(
        map(_perfomr_message, res["items"][::-1]),
        # map(lambda e: {
        #     'm_id':e['id'],
        #     'out':e['out'],
        #     'timestamp':e['date'],
        #     'body':e['body'],
        #     'read_state':e['read_state'],
        #     'strftime': datetime.fromtimestamp(e['date']).strftime('%H:%M:%S') # TODO: remove
        #     }, res['items'][::-1]
        # ),
        maxlen=MESSAGES_LIMIT,
    )


@autorun
@mark_as_deamon
class LongPoolThread(Thread):
    def __init__(self, vk: VK_api, notify_on: dict):
        super(self.__class__, self).__init__()
        self.vk = vk
        for k in list(notify_on.keys()):
            notify_on[k.value] = notify_on[k]
            del notify_on[k]
        self.notify_on = notify_on

    def run(self):
        while 1:
            # 2 - receive attachments
            # 64 - receive $extra fields in SET_ONLINE
            upd = self.vk.get_long_pool({"mode": 2 + 64})["updates"]
            redraw_page = False
            for event in upd:
                if event[0] in self.notify_on.keys():
                    # print('we got smthg', event[0],flush=True)
                    for observer in self.notify_on[event[0]]:
                        observer(event)
                    redraw_page = True
            if redraw_page:
                draw_page()


def message_handler(event):
    """
    message handler

    r =  [4, 243626, 17, 19549540, 1500025181, ' ... ', 'Й']

    r[0] $key == 4 -> message
    r[1] $message_id
    r[2] $flags == 1(unread) + !2 (outpbox) 
    r[3] $from_id
    r[4] $timestamp
    r[5] $title(?)
    r[6] $text
    """

    if not event[3] in WATCH_ON:
        return  # TODO: delete on release

    if not (event[2] & 1):  # only new
        return

    msg = {
        "m_id": event[1],
        "out": 1 if event[2] & 2 else 0,
        "timestamp": event[4],
        "body": html.unescape(event[6]).replace("<br>", "\n"),
        "strftime": datetime.fromtimestamp(event[4]).strftime(
            "%H:%M:%S"
        ),  # TODO: remove
    }
    try:
        GLOBAL_STATUS.messages[event[3]].append(msg)
    except:
        GLOBAL_STATUS.messages[event[3]] = deque([msg], maxlen=MESSAGES_LIMIT)


def onlien_offline_handler(event):
    """
    online-offline handler

    r = [8, -19549540, 0, 192415126]

    r[0] $key == 8/9 set online/offline
    r[1] -$user_id
    r[2] $extra
    r[3] timestamp
    """
    if not abs(event[1]) in WATCH_ON:
        return  # TODO: delete on release

    log_error(event)

    # print('-'*50)
    # print("here some update",flush=True)
    # print('-'*50)

    is_online = {
        "status": 1 if event[0] == EventType.SET_ONLINE else 0,
        "timestamp": event[3],
    }
    GLOBAL_STATUS.is_online[abs(event[1])] = is_online

    draw_page()


def main_loop():
    while 1:
        try:
            orig_query = None
            try:
                if GLOBAL_STATE.multiline_input:
                    orig_query = sys.stdin.read().strip()
                else:
                    orig_query = input()
            except EOFError:  # prevent ctrl + D to close program
                pass
            query = orig_query.strip().lower()
            if query == "q" or query == "exit":
                break
            force_redraw = user_input_handler(orig_query)
            draw_page(force_redraw)
            # DEBUG OPTIONS
            if query == "pdo":  # print-debug-online
                print(*GLOBAL_STATUS.is_online.items(), sep="\n")
            if query == "pdm":  # print-debug-messages
                print(GLOBAL_STATUS.messages)

        except KeyboardInterrupt:
            break
    return 0


def main():
    token = None
    # TODO: next 2 lines not secure and contains no check, add
    with open("key.token") as f:
        token = f.readline()

    global GLOBAL_VK
    GLOBAL_VK = VK_api(token)

    notify_on = {
        EventType.MESSAGE: [message_handler],
        EventType.SET_ONLINE: [onlien_offline_handler],
        EventType.SET_OFFLINE: [onlien_offline_handler],
    }
    lp = LongPoolThread(GLOBAL_VK, notify_on)
    draw_page()
    return main_loop()


if __name__ == "__main__":
    raise SystemExit(main())

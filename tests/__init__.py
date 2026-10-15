"""测试包初始化：把用户配置与系统凭据库换成临时/内存版本。
默认配置档与各提供方 key 都从这里读取，不隔离的话开发机上的真实设置会改变测试结果，测试也会写到真实凭据库。"""
import atexit
import os
import shutil
import tempfile

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from api import config_store


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise PasswordDeleteError(username)
        del self.store[(service, username)]


_tmp = tempfile.mkdtemp(prefix="cat-tests-")
atexit.register(shutil.rmtree, _tmp, True)
config_store._CONFIG_FILE = os.path.join(_tmp, "user_config.json")
keyring.set_keyring(MemoryKeyring())

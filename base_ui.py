from abc import abstractmethod, ABCMeta


class BaseStatusBar(metaclass=ABCMeta):
    @abstractmethod
    def update(self, text):
        pass

    @abstractmethod
    def clear(self):
        pass


class BaseWebsocketStatus(metaclass=ABCMeta):
    @abstractmethod
    def update(self, idx, status, topics):
        pass

    @abstractmethod
    def remove(self, idx):
        pass


class BaseLoginForm(metaclass=ABCMeta):
    @abstractmethod
    def clear(self, login, password, token):
        pass

    @abstractmethod
    def wait_for_login_press(self):
        pass

    @abstractmethod
    def ask_login(self):
        pass

    @abstractmethod
    def update(self, status, user_id):
        pass

    @abstractmethod
    def ask_enter_code(self, user_code):
        pass


class BaseTrayIcon(metaclass=ABCMeta):
    @abstractmethod
    def is_tray(self):
        pass

    @abstractmethod
    def get_title(self, drop):
        pass

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def stop(self):
        pass

    @abstractmethod
    def quit(self):
        pass

    @abstractmethod
    def minimize(self):
        pass

    @abstractmethod
    def restore(self):
        pass

    @abstractmethod
    def notify(self, message, title, duration):
        pass

    @abstractmethod
    def update_title(self, drop):
        pass


class BaseSettingsPanel(metaclass=ABCMeta):
    @abstractmethod
    def clear_selection(self):
        pass

    @abstractmethod
    def update_notifications(self):
        pass

    @abstractmethod
    def update_autostart(self):
        pass

    @abstractmethod
    def set_games(self, games):
        pass

    @abstractmethod
    def priorities(self):
        pass

    @abstractmethod
    def priority_add(self):
        pass

    @abstractmethod
    def priority_move(self, up):
        pass

    @abstractmethod
    def priority_delete(self):
        pass

    @abstractmethod
    def priority_only(self):
        pass

    @abstractmethod
    def exclude_add(self):
        pass

    @abstractmethod
    def exclude_delete(self):
        pass


class BaseInventoryOverview(metaclass=ABCMeta):
    @abstractmethod
    def refresh(self):
        pass

    @abstractmethod
    def add_campaign(self, campaign):
        pass

    @abstractmethod
    def clear(self):
        pass

    @staticmethod
    @abstractmethod
    def get_status(campaign):
        pass

    @staticmethod
    @abstractmethod
    def get_progress(drop):
        pass

    @abstractmethod
    def update_drop(self, drop):
        pass


class BaseCampaignProgress(metaclass=ABCMeta):
    @abstractmethod
    def start_timer(self):
        pass

    @abstractmethod
    def stop_timer(self):
        pass

    @abstractmethod
    def display(self, drop, countdown, subone):
        pass


class BaseConsoleOutput(metaclass=ABCMeta):
    @abstractmethod
    def print(self, message):
        pass


class BaseChannelList(metaclass=ABCMeta):
    @abstractmethod
    def shrink(self):
        pass

    @abstractmethod
    def clear_watching(self):
        pass

    @abstractmethod
    def set_watching(self, channel):
        pass

    @abstractmethod
    def get_selection(self):
        pass

    @abstractmethod
    def clear_selection(self):
        pass

    @abstractmethod
    def clear(self):
        pass

    @abstractmethod
    def display(self, channel, add):
        pass

    @abstractmethod
    def remove(self, channel):
        pass


class BaseInterfaceManager(metaclass=ABCMeta):
    @abstractmethod
    def wnd_proc(self, hwnd, msg, w_param, l_param):
        """
        This function serves as a message processor for all messages sent
        to the application by Windows.
        """
        pass

    @abstractmethod
    async def wait_until_closed(self):
        pass

    @abstractmethod
    async def coro_unless_closed(self, coro):
        pass

    @abstractmethod
    def prevent_close(self):
        pass

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def stop(self):
        pass

    @abstractmethod
    def close(self, args):
        """
        Requests the GUI application to close.
        The window itself will be closed in the closing sequence later.
        """
        pass

    @abstractmethod
    def close_window(self):
        """
        Closes the window. Invalidates the logger.
        """
        pass

    @abstractmethod
    def unfocus(self, event):
        pass

    @abstractmethod
    def save(self, force):
        pass

    @abstractmethod
    def set_games(self, games):
        pass

    @abstractmethod
    def display_drop(self, drop, countdown, subone):
        pass

    @abstractmethod
    def clear_drop(self):
        pass

    @abstractmethod
    def print(self, message):
        pass

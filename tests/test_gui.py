
import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

# Add project root to path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock pystray and winreg before they're imported by gui and registry
sys.modules['pystray'] = MagicMock()
sys.modules['winreg'] = MagicMock()

from translate import _
import gui
from registry import ValueType, ValueNotFound
import constants
from settings import Settings

@patch('translate._', lambda key, *args, **kwargs: key)
class TestSettingsPanel(unittest.TestCase):
    @patch('gui.ttk.Button')
    @patch('gui.PaddedListbox')
    @patch('gui.PlaceholderCombobox')
    @patch('gui.PlaceholderEntry')
    @patch('gui.SelectCombobox')
    @patch('gui.ttk.Checkbutton')
    @patch('gui.ttk.Label')
    @patch('gui.ttk.LabelFrame')
    @patch('gui.ttk.Frame')
    @patch('gui.tk.Tk')
    @patch('gui.tk.IntVar')
    @patch('gui.tk.StringVar')
    def setUp(self, mock_stringvar, mock_intvar, mock_tk, mock_frame, mock_labelframe, mock_label, mock_checkbutton,
              mock_selectcombobox, mock_placeholderentry, mock_placeholdercombobox,
              mock_paddedlistbox, mock_button):

        self.mock_twitch = MagicMock()
        # Provide a mock settings object
        self.mock_twitch.settings = MagicMock(spec=Settings)
        self.mock_twitch.settings.priority_mode = gui.PriorityMode.PRIORITY_ONLY
        self.mock_twitch.settings.proxy = ""
        self.mock_twitch.settings.autostart_tray = False
        self.mock_twitch.settings.dark_mode = False
        self.mock_twitch.settings.tray_notifications = True
        self.mock_twitch.settings.priority = []
        self.mock_twitch.settings.exclude = set()

        self.mock_gui_manager = MagicMock()
        self.mock_gui_manager._twitch = self.mock_twitch
        self.mock_gui_manager._root = mock_tk()

        # Some more mocks for init
        with patch('gui.nametofont'), patch('gui.Font'):
            self.settings_panel = gui.SettingsPanel(self.mock_gui_manager, self.mock_gui_manager._root)

    @patch('sys.platform', 'win32')
    @patch('registry.RegistryKey')
    def test_query_autostart_dev_unquoted(self, mock_registry_key):
        """
        Tests if _query_autostart can handle unquoted paths in a dev environment.
        This test should fail before the fix.
        """
        # Arrange
        constants.IS_PACKAGED = False  # Simulate dev environment
        mock_key_instance = mock_registry_key.return_value.__enter__.return_value

        # A possible registry value with unquoted paths
        unquoted_path = str(constants.SELF_PATH.resolve())
        registry_value = f"C:\\Python\\pythonw.exe {unquoted_path} --tray"
        mock_key_instance.get.return_value = (ValueType.REG_SZ, registry_value)

        # Act
        # The original implementation will fail because it checks for a quoted path.
        result = self.settings_panel._query_autostart()

        # Assert
        self.assertTrue(result, "Should return True for unquoted path in dev environment")


if __name__ == '__main__':
    unittest.main()

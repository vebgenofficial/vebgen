# backend/src/core/tests/mock_customtkinter.py

from unittest.mock import MagicMock, Mock

class MockCTkWidget(MagicMock):
    """A generic mock for any CustomTkinter widget."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Mock methods that are commonly called on widgets
        self.pack = MagicMock()
        self.place = MagicMock()
        self.grid = MagicMock()
        self.destroy = MagicMock()
        self.configure = MagicMock()
        self.bind = MagicMock()
        self.cget = MagicMock(return_value="") # Return empty string for cget by default
        self.winfo_exists = MagicMock(return_value=True)
        self.winfo_width = MagicMock(return_value=800)
        self.winfo_height = MagicMock(return_value=600)
        self._parent_canvas = MagicMock() # For CTkScrollableFrame

class MockCTk(Mock):
    """Mocks the customtkinter module."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.CTk = Mock(return_value=MockCTkWidget())
        self.CTkFrame = Mock(return_value=MockCTkWidget())
        self.CTkButton = Mock(return_value=MockCTkWidget())
        self.CTkLabel = Mock(return_value=MockCTkWidget())
        self.CTkEntry = Mock(return_value=MockCTkWidget())
        self.CTkComboBox = Mock(return_value=MockCTkWidget())
        self.CTkCheckBox = Mock(return_value=MockCTkWidget())
        self.CTkSlider = Mock(return_value=MockCTkWidget())
        self.CTkProgressBar = Mock(return_value=MockCTkWidget())
        self.CTkTabview = self._create_mock_tabview()
        self.CTkScrollableFrame = Mock(return_value=MockCTkWidget())
        self.CTkTextbox = Mock(return_value=MockCTkWidget())
        self.CTkImage = Mock(return_value=None) # Return None for images
        self.CTkFont = Mock(return_value=None)
        self.set_appearance_mode = MagicMock()
        self.set_default_color_theme = MagicMock()

    def _create_mock_tabview(self):
        tabview_instance = MockCTkWidget()
        tabview_instance.add = MagicMock(return_value=MockCTkWidget()) # .add() returns a frame
        tabview_instance.set = MagicMock()
        return Mock(return_value=tabview_instance)

mock_ctk = MockCTk()
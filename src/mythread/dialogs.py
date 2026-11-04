"""Small, keyboard accessible confirmation dialogs."""
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ClearLoginDialog(ModalScreen[bool]):
    BINDINGS = [('escape', 'cancel', '取消')]
    DEFAULT_CSS = '''
    ClearLoginDialog { align: center middle; background: $background 70%; }
    ClearLoginDialog > Vertical { width: 54; max-width: 95%; height: auto;
        padding: 1 2; border: round $warning; background: $surface; }
    ClearLoginDialog Static { height: auto; margin-bottom: 1; }
    ClearLoginDialog Horizontal { height: 3; }
    '''

    def compose(self):
        with Vertical():
            yield Static('清除登入資料？')
            yield Static('將關閉專用瀏覽器，清除本 APP 的登入資料與快取。之後需要重新登入；不影響日常 Chrome。', markup=False)
            with Horizontal():
                yield Button('取消', id='cancel-clear')
                yield Button('確認清除', id='confirm-clear', variant='warning')

    def on_mount(self):
        self.query_one('#cancel-clear', Button).focus()

    def action_cancel(self):
        self.dismiss(False)

    def on_button_pressed(self, event):
        event.stop()
        self.dismiss(event.button.id == 'confirm-clear')

"""Sistema visual sobrio y reutilizable para la aplicación."""

from PySide6.QtGui import QFont, QFontDatabase, QIcon

from core.runtime_paths import asset_path

COLORS = {
    "canvas": "#F5F7FA",
    "surface": "#FFFFFF",
    "sidebar": "#EEF2F7",
    "border": "#DDE3EA",
    "text": "#172033",
    "muted": "#647084",
    "navy": "#172B4D",
    "blue": "#416FA6",
    "blue_soft": "#E8F0FA",
    "green": "#2F7D5A",
    "green_soft": "#E7F4ED",
    "red": "#A64545",
}


def stylesheet() -> str:
    return """
    * { font-family: "Inter"; color: #172033; font-size: 13px; }
    QMainWindow, QWidget#root { background: #F5F7FA; }
    QFrame#sidebar { background: #EEF2F7; border-right: 1px solid #DDE3EA; }
    QLabel#brand { font-size: 18px; font-weight: 700; color: #172B4D; }
    QLabel#eyebrow { color: #416FA6; font-size: 11px; font-weight: 700; }
    QLabel#pageTitle { font-size: 26px; font-weight: 650; color: #172033; }
    QLabel#pageSubtitle, QLabel#muted { color: #647084; font-size: 13px; }
    QPushButton#navButton { background: transparent; text-align: left; padding: 10px 14px; border: 0; border-radius: 7px; color: #4F5D70; font-size: 13px; }
    QPushButton#navButton:hover { background: #E3E9F1; color: #172B4D; }
    QPushButton#navButton:checked { background: #DDE8F5; color: #172B4D; font-weight: 600; }
    QPushButton { background: #FFFFFF; border: 1px solid #D6DDE6; border-radius: 7px; padding: 8px 15px; font-size: 13px; }
    QPushButton:hover { background: #F7F9FC; border-color: #BAC5D2; }
    QPushButton:disabled { color: #9AA5B4; background: #F1F3F6; }
    QPushButton#primary { background: #172B4D; color: white; border-color: #172B4D; font-weight: 600; }
    QPushButton#primary:hover { background: #223B65; }
    QPushButton#danger { color: #A64545; }
    QFrame#panel { background: #FFFFFF; border: 1px solid #DDE3EA; border-radius: 10px; }
    QLabel#metric { font-size: 21px; font-weight: 650; color: #172B4D; }
    QLabel#sectionTitle { font-size: 14px; font-weight: 650; }
    QLabel#video { background: #101723; border: 1px solid #D1D8E2; border-radius: 9px; color: #AAB5C4; }
    QLabel#fpsBadge { background: #172B4D; color: white; border-radius: 5px; padding: 4px 8px; font-weight: 600; }
    QCheckBox { spacing: 9px; font-size: 13px; }
    QCheckBox::indicator { width: 34px; height: 18px; border-radius: 9px; border: 1px solid #B9C4D1; background: #CFD6DE; }
    QCheckBox::indicator:checked { background: #416FA6; border-color: #416FA6; }
    QComboBox, QLineEdit, QListWidget { background: white; border: 1px solid #D6DDE6; border-radius: 7px; padding: 7px 10px; min-height: 20px; }
    QComboBox:focus, QLineEdit:focus, QListWidget:focus { border-color: #7597BC; }
    QComboBox::drop-down { border: 0; width: 28px; }
    QProgressBar { background: #E8EDF3; border: 0; border-radius: 4px; height: 8px; text-align: center; color: transparent; }
    QProgressBar::chunk { background: #416FA6; border-radius: 4px; }
    QTextEdit, QTextBrowser { background: white; border: 1px solid #D6DDE6; border-radius: 8px; padding: 9px; selection-background-color: #C9D9EC; }
    QTextEdit:focus { border-color: #7597BC; }
    QScrollArea { border: 0; background: transparent; }
    QToolTip { background: #172B4D; color: white; border: 0; padding: 5px; }
    QWizard { background: #F5F7FA; }
    QWizardPage { background: #F5F7FA; }
    QWizard QLabel { background: transparent; }
    QWizard QPushButton { min-width: 86px; }
    QWizard QPushButton#primary { background: #172B4D; color: white; border-color: #172B4D; }
    QFrame#wizardSidebar { background: #172B4D; border: 0; }
    QLabel#wizardBrand { color: white; font-size: 19px; font-weight: 700; letter-spacing: 1px; }
    QLabel#wizardCaption { color: #AFC1D8; font-size: 12px; }
    QLabel#wizardStep { color: #91A5BF; padding: 9px 0; font-size: 12px; }
    QLabel#wizardStepActive { color: white; padding: 9px 0; font-size: 12px; font-weight: 650; }
    QSplashScreen#startupSplash { font-family: "Inter"; font-size: 12px; padding: 24px 34px; }
    """


def apply_theme(application) -> str:
    """Carga la tipografía y la identidad visual de forma determinista."""
    font_id = QFontDatabase.addApplicationFont(
        str(asset_path("fonts", "InterVariable.ttf"))
    )
    families = QFontDatabase.applicationFontFamilies(font_id)
    family = families[0] if families else "Segoe UI"
    application.setFont(QFont(family, 10))
    application.setWindowIcon(QIcon(str(asset_path("room_os.ico"))))
    application.setStyleSheet(stylesheet())
    return family

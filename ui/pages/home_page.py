from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from ui.components import PageHeader, StatusCard, section_panel


class HomePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 30)
        layout.setSpacing(22)
        layout.addWidget(PageHeader("Inicio", "Estado esencial de Room OS en tiempo real."))

        grid = QGridLayout()
        grid.setSpacing(12)
        self.cards = {
            "camera": StatusCard("Cámara", "Iniciando"),
            "ai": StatusCard("Gemini", "Comprobando"),
            "presence": StatusCard("Presencia", "Sin datos"),
            "gesture": StatusCard("Gesto", "Ninguno"),
        }
        for index, card in enumerate(self.cards.values()):
            grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(grid)

        note = QLabel(
            "La cámara y el análisis local permanecen activos. Abre una sección "
            "para ver detalles o ajustar su visualización."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(section_panel("Operación", note))
        layout.addStretch()

    def update_status(self, key: str, value: str) -> None:
        card = self.cards.get(key)
        if card is not None:
            card.set_value(value)


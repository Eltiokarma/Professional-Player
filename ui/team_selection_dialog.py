# src/ui/team_selection_dialog.py
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QMessageBox)
from sqlalchemy.orm import sessionmaker
from data.database_manager import engine
from data.data_models.teams import Team
from ui.ultra_fast_constants_window import ConstantsResultsWindow

Session = sessionmaker(bind=engine)

class TeamSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Seleccionar equipos para análisis")
        self.resize(500, 550)
        self._build_ui()
        self._load_teams()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        # Campo de búsqueda
        self.search = QLineEdit(placeholderText="Buscar equipo...")
        layout.addWidget(self.search)
        
        # Lista de equipos
        self.list = QListWidget(selectionMode=QListWidget.MultiSelection)
        layout.addWidget(self.list, 1)
        
        # Botón de confirmación
        btn_confirm = QPushButton("📊 Analizar equipos seleccionados")
        btn_confirm.setStyleSheet("""
            QPushButton {
                background-color: #007BFF;
                color: white;
                border: none;
                padding: 10px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0056B3;
            }
        """)
        layout.addWidget(btn_confirm)

        # Conectar señales
        self.search.textChanged.connect(self._filter)
        btn_confirm.clicked.connect(self._confirm)

    def _load_teams(self):
        """Carga todos los equipos en la lista"""
        session = Session()
        try:
            self.teams = session.query(Team).order_by(Team.name).all()
            for team in self.teams:
                item = QListWidgetItem(f"{team.name} (ID: {team.id})")
                item.setData(256, team.id)
                self.list.addItem(item)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error cargando equipos: {str(e)}")
        finally:
            session.close()

    def _filter(self, text):
        """Filtra los equipos según el texto de búsqueda"""
        text_lower = text.lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(text_lower not in item.text().lower())

    def _confirm(self):
        """Procesa la selección de equipos"""
        selected_ids = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.isSelected():
                selected_ids.append(item.data(256))
        
        if len(selected_ids) < 1:
            QMessageBox.warning(self, "Sin selección", "Por favor selecciona al menos un equipo.")
            return
        
        # Abrir ventana de análisis para cada equipo seleccionado
        for team_id in selected_ids:
            try:
                # Usar la ventana optimizada
                window = ConstantsResultsWindow(self.parent(), team_id)
                window.show()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error abriendo análisis para equipo {team_id}: {str(e)}")
        
        self.accept()
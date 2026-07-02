# ui/odds_viewer/styles/colors.py
# -*- coding: utf-8 -*-
"""
Paleta de colores para el sistema de odds y simulador.
Inspirado en casas de apuestas modernas (Betsson, DraftKings).
"""

class Colors:
    """Paleta de colores centralizada."""
    
    # === Estados de apuesta ===
    WIN = '#28A745'              # Verde - Ganó
    LOSS = '#DC3545'             # Rojo - Perdió
    VOID = '#FFC107'             # Amarillo - Void/Push
    PENDING = '#17A2B8'          # Cyan - Pendiente
    
    # === ROI ===
    ROI_POSITIVE = '#28A745'     # Verde
    ROI_NEGATIVE = '#DC3545'     # Rojo
    ROI_NEUTRAL = '#6C757D'      # Gris
    
    # === Tema principal ===
    PRIMARY = '#1a1a2e'          # Azul oscuro (headers)
    SECONDARY = '#16213e'        # Azul medio
    ACCENT = '#FF6B35'           # Naranja (destacados)
    ACCENT_HOVER = '#E55A2B'     # Naranja oscuro
    
    # === Fondos ===
    BACKGROUND = '#F8F9FA'       # Gris muy claro
    CARD = '#FFFFFF'             # Blanco
    CARD_HOVER = '#F0F4F8'       # Gris hover
    BORDER = '#DEE2E6'           # Borde gris
    
    # === Texto ===
    TEXT_PRIMARY = '#212529'     # Casi negro
    TEXT_SECONDARY = '#6C757D'   # Gris
    TEXT_LIGHT = '#FFFFFF'       # Blanco
    TEXT_MUTED = '#ADB5BD'       # Gris claro
    
    # === Cuotas ===
    ODD_FAVORABLE = '#28A745'    # Verde - cuota alta/value
    ODD_NORMAL = '#495057'       # Gris oscuro
    ODD_LOW = '#DC3545'          # Rojo - cuota muy baja
    ODD_BUTTON_BG = '#F8F9FA'    # Fondo botón cuota
    ODD_BUTTON_HOVER = '#E9ECEF' # Hover botón cuota
    
    # === Ubicación ===
    HOME = '#007BFF'             # Azul - Local
    AWAY = '#6F42C1'             # Morado - Visita
    
    # === Gráficos ===
    CHART_PRIMARY = '#007BFF'
    CHART_SECONDARY = '#28A745'
    CHART_TERTIARY = '#FFC107'
    CHART_QUATERNARY = '#DC3545'
    CHART_GRID = '#E9ECEF'
    
    # === Rankings ===
    GOLD = '#FFD700'
    SILVER = '#C0C0C0'
    BRONZE = '#CD7F32'
    
    @classmethod
    def get_roi_color(cls, roi: float) -> str:
        """Retorna color según ROI."""
        if roi > 5:
            return cls.ROI_POSITIVE
        elif roi < -5:
            return cls.ROI_NEGATIVE
        return cls.ROI_NEUTRAL
    
    @classmethod
    def get_odd_color(cls, odd: float) -> str:
        """Retorna color según valor de cuota."""
        if odd >= 3.0:
            return cls.ODD_FAVORABLE
        elif odd <= 1.3:
            return cls.ODD_LOW
        return cls.ODD_NORMAL
    
    @classmethod
    def get_result_color(cls, won: bool) -> str:
        """Retorna color según resultado."""
        return cls.WIN if won else cls.LOSS


class Styles:
    """Estilos CSS reutilizables."""
    
    MAIN_WINDOW = f"""
        QMainWindow {{
            background-color: {Colors.BACKGROUND};
        }}
    """
    
    CARD = f"""
        QFrame#card {{
            background-color: {Colors.CARD};
            border: 1px solid {Colors.BORDER};
            border-radius: 8px;
        }}
        QFrame#card:hover {{
            border-color: {Colors.ACCENT};
        }}
    """
    
    KPI_CARD = f"""
        QFrame#kpiCard {{
            background-color: {Colors.CARD};
            border: 1px solid {Colors.BORDER};
            border-radius: 12px;
            padding: 15px;
        }}
    """
    
    ODD_BUTTON = f"""
        QPushButton#oddButton {{
            background-color: {Colors.ODD_BUTTON_BG};
            border: 1px solid {Colors.BORDER};
            border-radius: 6px;
            padding: 10px 15px;
            font-size: 16px;
            font-weight: bold;
            color: {Colors.TEXT_PRIMARY};
            min-width: 70px;
        }}
        QPushButton#oddButton:hover {{
            background-color: {Colors.ODD_BUTTON_HOVER};
            border-color: {Colors.ACCENT};
        }}
        QPushButton#oddButton:pressed {{
            background-color: {Colors.ACCENT};
            color: {Colors.TEXT_LIGHT};
        }}
    """
    
    TAB_WIDGET = f"""
        QTabWidget::pane {{
            border: 1px solid {Colors.BORDER};
            background-color: {Colors.BACKGROUND};
            border-radius: 0 0 8px 8px;
        }}
        QTabBar::tab {{
            background-color: {Colors.CARD};
            border: 1px solid {Colors.BORDER};
            padding: 10px 20px;
            margin-right: 2px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
        }}
        QTabBar::tab:selected {{
            background-color: {Colors.PRIMARY};
            color: {Colors.TEXT_LIGHT};
            border-color: {Colors.PRIMARY};
        }}
        QTabBar::tab:hover:!selected {{
            background-color: {Colors.CARD_HOVER};
        }}
    """
    
    COMBO_BOX = f"""
        QComboBox {{
            padding: 8px 12px;
            border: 1px solid {Colors.BORDER};
            border-radius: 6px;
            background-color: {Colors.CARD};
            min-width: 150px;
        }}
        QComboBox:hover {{
            border-color: {Colors.ACCENT};
        }}
        QComboBox::drop-down {{
            border: none;
            padding-right: 10px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {Colors.CARD};
            border: 1px solid {Colors.BORDER};
            selection-background-color: {Colors.ACCENT};
        }}
    """
    
    SPIN_BOX = f"""
        QDoubleSpinBox, QSpinBox {{
            padding: 8px 12px;
            border: 1px solid {Colors.BORDER};
            border-radius: 6px;
            background-color: {Colors.CARD};
        }}
        QDoubleSpinBox:hover, QSpinBox:hover {{
            border-color: {Colors.ACCENT};
        }}
    """
    
    PRIMARY_BUTTON = f"""
        QPushButton#primaryButton {{
            background-color: {Colors.ACCENT};
            color: {Colors.TEXT_LIGHT};
            border: none;
            border-radius: 6px;
            padding: 12px 24px;
            font-size: 14px;
            font-weight: bold;
        }}
        QPushButton#primaryButton:hover {{
            background-color: {Colors.ACCENT_HOVER};
        }}
        QPushButton#primaryButton:pressed {{
            background-color: #CC4A20;
        }}
        QPushButton#primaryButton:disabled {{
            background-color: {Colors.TEXT_MUTED};
        }}
    """
    
    SECONDARY_BUTTON = f"""
        QPushButton#secondaryButton {{
            background-color: {Colors.CARD};
            color: {Colors.TEXT_PRIMARY};
            border: 1px solid {Colors.BORDER};
            border-radius: 6px;
            padding: 10px 20px;
            font-size: 13px;
        }}
        QPushButton#secondaryButton:hover {{
            background-color: {Colors.CARD_HOVER};
            border-color: {Colors.ACCENT};
        }}
    """
    
    TABLE_VIEW = f"""
        QTableView {{
            background-color: {Colors.CARD};
            border: 1px solid {Colors.BORDER};
            border-radius: 8px;
            gridline-color: {Colors.BORDER};
            selection-background-color: {Colors.ACCENT};
        }}
        QTableView::item {{
            padding: 8px;
        }}
        QTableView::item:selected {{
            color: {Colors.TEXT_LIGHT};
        }}
        QHeaderView::section {{
            background-color: {Colors.PRIMARY};
            color: {Colors.TEXT_LIGHT};
            padding: 10px;
            border: none;
            font-weight: bold;
        }}
    """
    
    SCROLL_AREA = f"""
        QScrollArea {{
            border: none;
            background-color: transparent;
        }}
        QScrollBar:vertical {{
            background-color: {Colors.BACKGROUND};
            width: 10px;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {Colors.TEXT_MUTED};
            border-radius: 5px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {Colors.TEXT_SECONDARY};
        }}
    """
    
    @classmethod
    def get_all_styles(cls) -> str:
        """Combina todos los estilos."""
        return "\n".join([
            cls.MAIN_WINDOW,
            cls.CARD,
            cls.KPI_CARD,
            cls.ODD_BUTTON,
            cls.TAB_WIDGET,
            cls.COMBO_BOX,
            cls.SPIN_BOX,
            cls.PRIMARY_BUTTON,
            cls.SECONDARY_BUTTON,
            cls.TABLE_VIEW,
            cls.SCROLL_AREA,
        ])

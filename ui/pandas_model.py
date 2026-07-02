from PySide6.QtCore import QAbstractTableModel, Qt

class PandasModel(QAbstractTableModel):
    def __init__(self, df):
        super().__init__()
        self._df = df

    def rowCount(self, *_):
        return len(self._df)

    def columnCount(self, *_):
        return len(self._df.columns)

    def data(self, idx, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            val = self._df.iat[idx.row(), idx.column()]
            return "" if val is None else (f"{val:.2f}" if isinstance(val, float) else str(val))
        return None

    def headerData(self, sec, orient, role):
        if role == Qt.DisplayRole:
            return self._df.columns[sec] if orient == Qt.Horizontal else str(sec)
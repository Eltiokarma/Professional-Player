#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tickets_manager.py

Sistema de Gestion de Tickets de Apuestas
==========================================

Base de datos SQLite para registrar y trackear apuestas.
Permite multiples tickets por partido, resolucion automatica
cruzando con sad.db, y estadisticas completas.

Autor: Gerson (desarrollado con Claude)
Fecha: Febrero 2026
"""

import os
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Text
from sqlalchemy.orm import sessionmaker
try:
    from sqlalchemy.orm import declarative_base
except ImportError:
    from sqlalchemy.ext.declarative import declarative_base

logger = logging.getLogger(__name__)

Base = declarative_base()


class Ticket(Base):
    """Modelo de ticket de apuesta."""
    __tablename__ = 'tickets'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Informacion del partido
    fixture_id = Column(Integer, nullable=False, index=True)
    home_team_name = Column(String(100), nullable=False)
    away_team_name = Column(String(100), nullable=False)
    match_date = Column(DateTime, nullable=True)
    league_name = Column(String(100), nullable=True)
    league_id = Column(Integer, nullable=True)

    # Informacion de la apuesta
    bet_type = Column(String(50), nullable=False)         # 1X2, O/U, BTTS, Handicap, Marcador
    bet_selection = Column(String(100), nullable=False)    # 1, X, 2, Over 2.5, etc.
    odds = Column(Float, nullable=False)                   # Cuota
    stake = Column(Float, nullable=False)                  # Monto apostado
    potential_return = Column(Float, nullable=False)        # Ganancia potencial
    bookmaker = Column(String(100), nullable=True)         # Casa de apuestas

    # Estado y resultado
    status = Column(String(20), default='pending')         # pending, won, lost, void, cashout
    actual_result = Column(String(100), nullable=True)     # Resultado real (ej: "2-1")
    profit_loss = Column(Float, nullable=True)             # Ganancia/perdida real

    # Metadatos
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    notes = Column(Text, nullable=True)

    # ML Score al momento de crear
    ml_score = Column(Float, nullable=True)
    recommendation = Column(String(100), nullable=True)

    def to_dict(self) -> Dict:
        """Convierte el ticket a diccionario."""
        return {
            'id': self.id,
            'fixture_id': self.fixture_id,
            'home_team_name': self.home_team_name,
            'away_team_name': self.away_team_name,
            'match_date': self.match_date.isoformat() if self.match_date else None,
            'league_name': self.league_name,
            'league_id': self.league_id,
            'bet_type': self.bet_type,
            'bet_selection': self.bet_selection,
            'odds': self.odds,
            'stake': self.stake,
            'potential_return': self.potential_return,
            'bookmaker': self.bookmaker,
            'status': self.status,
            'actual_result': self.actual_result,
            'profit_loss': self.profit_loss,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'notes': self.notes,
            'ml_score': self.ml_score,
            'recommendation': self.recommendation,
        }


class TicketsManager:
    """Gestor de tickets de apuestas."""

    def __init__(self, tickets_db_path: str, sad_db_path: str = None):
        """
        Inicializa el gestor de tickets.

        Args:
            tickets_db_path: Ruta a tickets.db
            sad_db_path: Ruta a sad.db (para resolucion automatica)
        """
        self.tickets_db_path = tickets_db_path
        self.sad_db_path = sad_db_path

        self.engine = create_engine(f'sqlite:///{tickets_db_path}', echo=False)
        self.Session = sessionmaker(bind=self.engine)

        # Crear tablas si no existen
        Base.metadata.create_all(self.engine)

        # Migrar bookmaker si la tabla ya existia sin el campo
        self._migrate_bookmaker_column()

        logger.info(f"TicketsManager inicializado: {tickets_db_path}")

    def _migrate_bookmaker_column(self):
        """Agrega columna bookmaker si no existe (migracion)."""
        import sqlite3
        conn = sqlite3.connect(self.tickets_db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(tickets)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'bookmaker' not in columns:
                cursor.execute("ALTER TABLE tickets ADD COLUMN bookmaker TEXT")
                conn.commit()
                logger.info("Migrado: columna 'bookmaker' agregada a tickets")
        except Exception as e:
            logger.warning(f"Error en migracion bookmaker: {e}")
        finally:
            conn.close()

    # =========================================================================
    # CRUD
    # =========================================================================

    def create_ticket(self, **kwargs) -> Optional[Ticket]:
        """Crea un nuevo ticket."""
        session = self.Session()
        try:
            # Calcular retorno potencial si no se proporciona
            if 'potential_return' not in kwargs:
                kwargs['potential_return'] = kwargs.get('stake', 0) * kwargs.get('odds', 0)

            ticket = Ticket(**kwargs)
            session.add(ticket)
            session.commit()
            session.refresh(ticket)
            logger.info(f"Ticket #{ticket.id} creado: {ticket.bet_type} {ticket.bet_selection} @{ticket.odds}")
            return ticket
        except Exception as e:
            session.rollback()
            logger.error(f"Error creando ticket: {e}")
            return None
        finally:
            session.close()

    def get_ticket(self, ticket_id: int) -> Optional[Ticket]:
        """Obtiene un ticket por ID."""
        session = self.Session()
        try:
            return session.query(Ticket).filter(Ticket.id == ticket_id).first()
        finally:
            session.close()

    def get_tickets_by_fixture(self, fixture_id: int) -> List[Ticket]:
        """Obtiene todos los tickets de un partido."""
        session = self.Session()
        try:
            return session.query(Ticket).filter(
                Ticket.fixture_id == fixture_id
            ).order_by(Ticket.created_at.desc()).all()
        finally:
            session.close()

    def get_pending_tickets(self) -> List[Ticket]:
        """Obtiene todos los tickets pendientes."""
        session = self.Session()
        try:
            return session.query(Ticket).filter(
                Ticket.status == 'pending'
            ).order_by(Ticket.match_date.asc()).all()
        finally:
            session.close()

    def get_all_tickets(self, limit: int = 5000) -> List[Ticket]:
        """Obtiene todos los tickets."""
        session = self.Session()
        try:
            return session.query(Ticket).order_by(
                Ticket.created_at.desc()
            ).limit(limit).all()
        finally:
            session.close()

    def get_filtered_tickets(
        self,
        status: str = None,
        league_name: str = None,
        bet_type: str = None,
        bookmaker: str = None,
        date_from: datetime = None,
        date_to: datetime = None,
    ) -> List[Ticket]:
        """Obtiene tickets con filtros."""
        session = self.Session()
        try:
            q = session.query(Ticket)
            if status and status != 'Todos':
                q = q.filter(Ticket.status == status)
            if league_name and league_name != 'Todas':
                q = q.filter(Ticket.league_name == league_name)
            if bet_type and bet_type != 'Todos':
                q = q.filter(Ticket.bet_type == bet_type)
            if bookmaker and bookmaker != 'Todos':
                q = q.filter(Ticket.bookmaker == bookmaker)
            if date_from:
                q = q.filter(Ticket.match_date >= date_from)
            if date_to:
                q = q.filter(Ticket.match_date <= date_to)
            return q.order_by(Ticket.created_at.desc()).all()
        finally:
            session.close()

    def update_ticket_status(
        self,
        ticket_id: int,
        status: str,
        actual_result: str = None,
    ) -> bool:
        """Actualiza el estado de un ticket y calcula profit/loss."""
        session = self.Session()
        try:
            ticket = session.query(Ticket).filter(Ticket.id == ticket_id).first()
            if not ticket:
                return False

            ticket.status = status
            if actual_result:
                ticket.actual_result = actual_result

            if status == 'won':
                ticket.profit_loss = ticket.potential_return - ticket.stake
            elif status == 'lost':
                ticket.profit_loss = -ticket.stake
            elif status == 'void':
                ticket.profit_loss = 0.0
            elif status == 'cashout':
                pass  # Se establece manualmente

            ticket.updated_at = datetime.now()
            session.commit()
            logger.info(f"Ticket #{ticket_id} -> {status}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Error actualizando ticket: {e}")
            return False
        finally:
            session.close()

    def duplicate_ticket(self, ticket_id: int) -> Optional[Ticket]:
        """Duplica un ticket existente (mismo fixture) con status pending."""
        session = self.Session()
        try:
            original = session.query(Ticket).filter(Ticket.id == ticket_id).first()
            if not original:
                return None

            new_ticket = Ticket(
                fixture_id=original.fixture_id,
                home_team_name=original.home_team_name,
                away_team_name=original.away_team_name,
                match_date=original.match_date,
                league_name=original.league_name,
                league_id=original.league_id,
                bet_type=original.bet_type,
                bet_selection=original.bet_selection,
                odds=original.odds,
                stake=original.stake,
                potential_return=original.potential_return,
                bookmaker=original.bookmaker,
                status='pending',
                ml_score=original.ml_score,
                recommendation=original.recommendation,
                notes=f"Duplicado de #{original.id}",
            )
            session.add(new_ticket)
            session.commit()
            session.refresh(new_ticket)
            logger.info(f"Ticket #{original.id} duplicado -> #{new_ticket.id}")
            return new_ticket
        except Exception as e:
            session.rollback()
            logger.error(f"Error duplicando ticket: {e}")
            return None
        finally:
            session.close()

    def delete_ticket(self, ticket_id: int) -> bool:
        """Elimina un ticket."""
        session = self.Session()
        try:
            ticket = session.query(Ticket).filter(Ticket.id == ticket_id).first()
            if not ticket:
                return False
            session.delete(ticket)
            session.commit()
            logger.info(f"Ticket #{ticket_id} eliminado")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Error eliminando ticket: {e}")
            return False
        finally:
            session.close()

    # =========================================================================
    # RESOLUCION AUTOMATICA
    # =========================================================================

    def resolve_pending_tickets(self) -> Dict:
        """
        Resuelve automaticamente tickets pendientes cruzando con sad.db.

        Returns:
            Dict con conteos de resueltos por status
        """
        if not self.sad_db_path or not os.path.exists(self.sad_db_path):
            logger.warning("sad.db no disponible para resolucion")
            return {'resolved': 0, 'won': 0, 'lost': 0, 'errors': 0}

        import sqlite3
        pending = self.get_pending_tickets()
        if not pending:
            return {'resolved': 0, 'won': 0, 'lost': 0, 'errors': 0}

        # Obtener resultados de sad.db
        fixture_ids = list(set(t.fixture_id for t in pending))
        conn = sqlite3.connect(self.sad_db_path)
        cursor = conn.cursor()

        results = {}
        for fid in fixture_ids:
            cursor.execute(
                "SELECT goals_home, goals_away, status_short FROM fixtures WHERE id = ?",
                (fid,)
            )
            row = cursor.fetchone()
            if row and row[2] in ('FT', 'AET', 'PEN'):
                results[fid] = {'goals_home': row[0], 'goals_away': row[1]}
        conn.close()

        stats = {'resolved': 0, 'won': 0, 'lost': 0, 'errors': 0}

        for ticket in pending:
            if ticket.fixture_id not in results:
                continue  # Partido no terminado

            r = results[ticket.fixture_id]
            gh, ga = r['goals_home'], r['goals_away']
            actual_result = f"{gh}-{ga}"

            try:
                won = self._evaluate_bet(ticket, gh, ga)
                if won is None:
                    continue  # No se pudo evaluar

                status = 'won' if won else 'lost'
                self.update_ticket_status(ticket.id, status, actual_result)
                stats['resolved'] += 1
                stats[status] += 1
            except Exception as e:
                logger.error(f"Error resolviendo ticket #{ticket.id}: {e}")
                stats['errors'] += 1

        logger.info(f"Resolucion: {stats}")
        return stats

    def _evaluate_bet(self, ticket: Ticket, goals_home: int, goals_away: int) -> Optional[bool]:
        """
        Evalua si un ticket gano o perdio basado en el resultado.

        Returns:
            True si gano, False si perdio, None si no se puede evaluar
        """
        bt = ticket.bet_type
        sel = ticket.bet_selection

        if bt == '1X2':
            if '1' in sel or 'Local' in sel:
                return goals_home > goals_away
            elif 'X' in sel or 'Empate' in sel:
                return goals_home == goals_away
            elif '2' in sel or 'Visita' in sel:
                return goals_away > goals_home

        elif bt == 'O/U':
            total = goals_home + goals_away
            sel_lower = sel.lower()
            # Extraer el numero: "Over 2.5" -> 2.5
            import re
            match = re.search(r'(\d+\.?\d*)', sel)
            if match:
                line = float(match.group(1))
                if 'over' in sel_lower:
                    return total > line
                elif 'under' in sel_lower:
                    return total < line

        elif bt == 'BTTS':
            both_scored = (goals_home > 0 and goals_away > 0)
            # Normalizar: quitar tildes para comparar
            import unicodedata
            sel_norm = unicodedata.normalize('NFD', sel.lower())
            sel_norm = ''.join(c for c in sel_norm if unicodedata.category(c) != 'Mn')
            if 'si' in sel_norm or 'yes' in sel_norm:
                return both_scored
            elif 'no' in sel_norm:
                return not both_scored

        elif bt == 'Handicap':
            # Formato: "Local -1", "Visita +1"
            import re
            match = re.search(r'([+-]?\d+\.?\d*)', sel)
            if match:
                handicap = float(match.group(1))
                sel_lower = sel.lower()
                if 'local' in sel_lower:
                    return (goals_home + handicap) > goals_away
                elif 'visita' in sel_lower:
                    return (goals_away + handicap) > goals_home

        elif bt == 'Marcador':
            # Formato: "2-1"
            import re
            match = re.match(r'(\d+)\s*-\s*(\d+)', sel)
            if match:
                pred_h = int(match.group(1))
                pred_a = int(match.group(2))
                return (goals_home == pred_h and goals_away == pred_a)

        return None  # No se pudo evaluar

    # =========================================================================
    # ESTADISTICAS
    # =========================================================================

    def get_summary(self) -> Dict:
        """Obtiene resumen global de estadisticas."""
        session = self.Session()
        try:
            all_tickets = session.query(Ticket).all()

            total = len(all_tickets)
            won = sum(1 for t in all_tickets if t.status == 'won')
            lost = sum(1 for t in all_tickets if t.status == 'lost')
            pending = sum(1 for t in all_tickets if t.status == 'pending')
            void = sum(1 for t in all_tickets if t.status == 'void')

            total_stake = sum(t.stake for t in all_tickets if t.status != 'pending')
            total_profit = sum(t.profit_loss or 0 for t in all_tickets if t.status in ('won', 'lost'))
            pending_stake = sum(t.stake for t in all_tickets if t.status == 'pending')

            win_rate = (won / (won + lost) * 100) if (won + lost) > 0 else 0
            roi = (total_profit / total_stake * 100) if total_stake > 0 else 0

            return {
                'total': total, 'won': won, 'lost': lost,
                'pending': pending, 'void': void,
                'win_rate': win_rate, 'roi': roi,
                'total_stake': total_stake,
                'total_profit': total_profit,
                'pending_stake': pending_stake,
            }
        finally:
            session.close()

    def get_bankroll_evolution(self) -> List[Dict]:
        """Calcula la evolucion del bankroll (profit acumulado)."""
        session = self.Session()
        try:
            tickets = session.query(Ticket).filter(
                Ticket.status.in_(['won', 'lost'])
            ).order_by(Ticket.match_date.asc(), Ticket.created_at.asc()).all()

            evolution = []
            cumulative = 0.0
            for t in tickets:
                cumulative += (t.profit_loss or 0)
                evolution.append({
                    'date': t.match_date or t.created_at,
                    'profit_loss': t.profit_loss or 0,
                    'cumulative': cumulative,
                    'ticket_id': t.id,
                    'match': f"{t.home_team_name} vs {t.away_team_name}",
                })
            return evolution
        finally:
            session.close()

    def get_roi_by_bet_type(self) -> Dict:
        """ROI desglosado por tipo de apuesta."""
        session = self.Session()
        try:
            tickets = session.query(Ticket).filter(
                Ticket.status.in_(['won', 'lost'])
            ).all()

            data = {}
            for t in tickets:
                bt = t.bet_type or 'Otro'
                if bt not in data:
                    data[bt] = {'stake': 0, 'profit': 0, 'won': 0, 'lost': 0}
                data[bt]['stake'] += t.stake
                data[bt]['profit'] += (t.profit_loss or 0)
                if t.status == 'won':
                    data[bt]['won'] += 1
                else:
                    data[bt]['lost'] += 1

            result = {}
            for bt, d in data.items():
                total = d['won'] + d['lost']
                result[bt] = {
                    'roi': (d['profit'] / d['stake'] * 100) if d['stake'] > 0 else 0,
                    'win_rate': (d['won'] / total * 100) if total > 0 else 0,
                    'total': total,
                    'profit': d['profit'],
                }
            return result
        finally:
            session.close()

    def get_win_rate_by_league(self) -> Dict:
        """Win rate desglosado por liga."""
        session = self.Session()
        try:
            tickets = session.query(Ticket).filter(
                Ticket.status.in_(['won', 'lost'])
            ).all()

            data = {}
            for t in tickets:
                lg = t.league_name or 'Desconocida'
                if lg not in data:
                    data[lg] = {'won': 0, 'lost': 0, 'profit': 0, 'stake': 0}
                data[lg]['stake'] += t.stake
                data[lg]['profit'] += (t.profit_loss or 0)
                if t.status == 'won':
                    data[lg]['won'] += 1
                else:
                    data[lg]['lost'] += 1

            result = {}
            for lg, d in data.items():
                total = d['won'] + d['lost']
                result[lg] = {
                    'win_rate': (d['won'] / total * 100) if total > 0 else 0,
                    'roi': (d['profit'] / d['stake'] * 100) if d['stake'] > 0 else 0,
                    'total': total,
                    'profit': d['profit'],
                }
            return result
        finally:
            session.close()

    def get_yield_by_odds_range(self) -> Dict:
        """Yield desglosado por rango de cuota."""
        session = self.Session()
        try:
            tickets = session.query(Ticket).filter(
                Ticket.status.in_(['won', 'lost'])
            ).all()

            ranges = [
                ('1.01-1.50', 1.01, 1.50),
                ('1.51-2.00', 1.51, 2.00),
                ('2.01-2.50', 2.01, 2.50),
                ('2.51-3.00', 2.51, 3.00),
                ('3.01-4.00', 3.01, 4.00),
                ('4.01+', 4.01, 999),
            ]

            result = {}
            for label, low, high in ranges:
                subset = [t for t in tickets if low <= (t.odds or 0) <= high]
                if not subset:
                    result[label] = {'yield_pct': 0, 'win_rate': 0, 'total': 0, 'profit': 0}
                    continue
                stake = sum(t.stake for t in subset)
                profit = sum(t.profit_loss or 0 for t in subset)
                won = sum(1 for t in subset if t.status == 'won')
                total = len(subset)
                result[label] = {
                    'yield_pct': (profit / stake * 100) if stake > 0 else 0,
                    'win_rate': (won / total * 100) if total > 0 else 0,
                    'total': total,
                    'profit': profit,
                }
            return result
        finally:
            session.close()

    def get_ml_score_correlation(self) -> List[Dict]:
        """Correlacion entre ml_score y resultado."""
        session = self.Session()
        try:
            tickets = session.query(Ticket).filter(
                Ticket.status.in_(['won', 'lost']),
                Ticket.ml_score.isnot(None),
            ).all()

            return [{
                'ml_score': t.ml_score,
                'won': 1 if t.status == 'won' else 0,
                'odds': t.odds,
                'profit_loss': t.profit_loss or 0,
                'bet_type': t.bet_type,
            } for t in tickets]
        finally:
            session.close()

    def get_unique_values(self, field: str) -> List[str]:
        """Obtiene valores unicos de un campo para filtros."""
        session = self.Session()
        try:
            col = getattr(Ticket, field, None)
            if col is None:
                return []
            rows = session.query(col).distinct().all()
            return sorted([r[0] for r in rows if r[0]])
        finally:
            session.close()

    def export_to_csv(self, filepath: str, tickets: List[Ticket] = None) -> bool:
        """Exporta tickets a CSV."""
        try:
            if tickets is None:
                tickets = self.get_all_tickets()

            import csv
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'ID', 'Fecha', 'Liga', 'Local', 'Visitante',
                    'Tipo', 'Seleccion', 'Cuota', 'Casa', 'Monto',
                    'Retorno', 'Status', 'Resultado', 'P/L',
                    'ML Score', 'Notas'
                ])
                for t in tickets:
                    writer.writerow([
                        t.id,
                        t.match_date.strftime('%Y-%m-%d %H:%M') if t.match_date else '',
                        t.league_name or '',
                        t.home_team_name, t.away_team_name,
                        t.bet_type, t.bet_selection,
                        f"{t.odds:.2f}", t.bookmaker or '',
                        f"{t.stake:.2f}", f"{t.potential_return:.2f}",
                        t.status, t.actual_result or '',
                        f"{t.profit_loss:.2f}" if t.profit_loss is not None else '',
                        f"{t.ml_score:.3f}" if t.ml_score is not None else '',
                        t.notes or '',
                    ])
            logger.info(f"Exportado {len(tickets)} tickets a {filepath}")
            return True
        except Exception as e:
            logger.error(f"Error exportando: {e}")
            return False


# Singleton global
_manager_instance = None


def _find_project_root() -> str:
    """Busca la carpeta donde vive tickets.db subiendo niveles."""
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.exists(os.path.join(current, 'tickets.db')):
            return current
        current = os.path.dirname(current)
    # Fallback: mismo directorio que este archivo
    return os.path.dirname(os.path.abspath(__file__))


def _find_sad_db() -> str:
    """Busca sad.db subiendo niveles (puede estar fuera de src/)."""
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.exists(os.path.join(current, 'sad.db')):
            return os.path.join(current, 'sad.db')
        current = os.path.dirname(current)
    return None


def get_tickets_manager(tickets_db_path: str = None, sad_db_path: str = None) -> TicketsManager:
    """Obtiene la instancia global del gestor de tickets."""
    global _manager_instance
    if _manager_instance is None:
        if tickets_db_path is None:
            base = _find_project_root()
            tickets_db_path = os.path.join(base, 'tickets.db')
            if sad_db_path is None:
                sad_db_path = _find_sad_db()
            logger.info(f"Tickets DB resuelta en: {tickets_db_path}")
            logger.info(f"SAD DB resuelta en: {sad_db_path}")
        _manager_instance = TicketsManager(tickets_db_path, sad_db_path)
    return _manager_instance
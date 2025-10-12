import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from ..models.chat import Chat
from ..models.message_log import MessageLog
from ..models.warning import Warning
from ..models.ban import Ban
from ..models.statistic import Statistic


class StatisticsService:
    """
    Сервис статистики работы бота (F3.2)
    
    Функции:
    - Получение статистики по чату
    - Генерация отчетов о работе бота
    - Сохранение агрегированной статистики
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    async def get_chat_statistics(self, chat_id: int, db: Session, days: int = 7) -> Dict[str, Any]:
        """
        Получить статистику по чату за N дней
        
        Args:
            chat_id: ID чата
            db: Сессия БД
            days: Количество дней для анализа
            
        Returns:
            Словарь со статистикой
        """
        try:
            start_date = datetime.now() - timedelta(days=days)
            
            # Базовая статистика сообщений
            total_messages = self._count_messages(db, chat_id, start_date)
            total_spam = self._count_spam_messages(db, chat_id, start_date)
            total_warnings = self._count_warnings(db, chat_id, start_date)
            total_bans = self._count_bans(db, chat_id, start_date)
            
            # Расчет процентов
            spam_percentage = (total_spam / total_messages * 100) if total_messages > 0 else 0.0
            
            # Статистика по детекторам (только F1.1 и F1.2)
            detector_stats = self._get_detector_statistics(db, chat_id, start_date)
            
            # Статистика по времени (почасовая активность)
            hourly_stats = self._get_hourly_statistics(db, chat_id, start_date)
            
            # Топ нарушителей
            top_violators = self._get_top_violators(db, chat_id, start_date)
            
            stats = {
                "period_days": days,
                "start_date": start_date.strftime("%Y-%m-%d %H:%M"),
                "end_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                
                # Основные метрики
                "total_messages": total_messages,
                "total_spam": total_spam,
                "total_warnings": total_warnings,
                "total_bans": total_bans,
                "spam_percentage": round(spam_percentage, 2),
                
                # Детальная статистика
                "detector_stats": detector_stats,
                "hourly_activity": hourly_stats,
                "top_violators": top_violators,
                
                # Эффективность модерации
                "moderation_efficiency": self._calculate_efficiency(total_messages, total_spam, total_warnings)
            }
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении статистики чата {chat_id}: {e}")
            raise
    
    def _count_messages(self, db: Session, chat_id: int, start_date: datetime) -> int:
        """Подсчет общего количества сообщений"""
        return db.query(MessageLog).filter(
            MessageLog.chat_id == chat_id,
            MessageLog.created_at >= start_date
        ).count()
    
    def _count_spam_messages(self, db: Session, chat_id: int, start_date: datetime) -> int:
        """Подсчет спам-сообщений"""
        return db.query(MessageLog).filter(
            MessageLog.chat_id == chat_id,
            MessageLog.created_at >= start_date,
            MessageLog.is_spam == True
        ).count()
    
    def _count_warnings(self, db: Session, chat_id: int, start_date: datetime) -> int:
        """Подсчет предупреждений"""
        return db.query(Warning).filter(
            Warning.chat_id == chat_id,
            Warning.issued_at >= start_date
        ).count()
    
    def _count_bans(self, db: Session, chat_id: int, start_date: datetime) -> int:
        """Подсчет банов/мутов"""
        return db.query(Ban).filter(
            Ban.chat_id == chat_id,
            Ban.issued_at >= start_date,
            Ban.action.in_(["ban", "mute"])
        ).count()
    
    def _get_detector_statistics(self, db: Session, chat_id: int, start_date: datetime) -> Dict[str, int]:
        """
        Статистика срабатывания детекторов
        
        Только F1.1 (ML-классификатор) и F1.2 (ссылки)
        """
        # TODO: Для полноценной статистики нужно добавить поле detected_by в MessageLog
        # Пока возвращаем заглушку с правильными детекторами
        
        return {
            "BayesClassifier": 0,     # F1.1 - ML-классификатор
            "LinkSpamDetector": 0,    # F1.2 - детектор ссылок
        }
    
    def _get_hourly_statistics(self, db: Session, chat_id: int, start_date: datetime) -> List[Dict[str, Any]]:
        """Почасовая статистика активности"""
        try:
            # Группируем сообщения по часам
            hourly_data = db.query(
                func.extract('hour', MessageLog.created_at).label('hour'),
                func.count(MessageLog.id).label('total'),
                func.sum(func.cast(MessageLog.is_spam, db.bind.dialect.name == 'sqlite' and 'INTEGER' or 'INT')).label('spam')
            ).filter(
                MessageLog.chat_id == chat_id,
                MessageLog.created_at >= start_date
            ).group_by(
                func.extract('hour', MessageLog.created_at)
            ).all()
            
            # Преобразуем в список словарей
            stats = []
            for hour, total, spam in hourly_data:
                spam_count = spam or 0
                stats.append({
                    "hour": int(hour),
                    "total_messages": total,
                    "spam_messages": spam_count,
                    "spam_percentage": round((spam_count / total * 100) if total > 0 else 0, 1)
                })
            
            return sorted(stats, key=lambda x: x['hour'])
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении почасовой статистики: {e}")
            return []
    
    def _get_top_violators(self, db: Session, chat_id: int, start_date: datetime, limit: int = 5) -> List[Dict[str, Any]]:
        """Топ нарушителей по количеству предупреждений"""
        try:
            violators = db.query(
                Warning.user_id,
                func.count(Warning.id).label('warning_count')
            ).filter(
                Warning.chat_id == chat_id,
                Warning.issued_at >= start_date
            ).group_by(
                Warning.user_id
            ).order_by(
                func.count(Warning.id).desc()
            ).limit(limit).all()
            
            result = []
            for user_id, warning_count in violators:
                result.append({
                    "user_id": user_id,
                    "warning_count": warning_count
                })
            
            return result
            
        except Exception as e:
            self.logger.error(f"Ошибка при получении топа нарушителей: {e}")
            return []
    
    def _calculate_efficiency(self, total_messages: int, spam_detected: int, warnings_issued: int) -> Dict[str, float]:
        """Расчет эффективности модерации"""
        detection_rate = (spam_detected / total_messages * 100) if total_messages > 0 else 0
        action_rate = (warnings_issued / spam_detected * 100) if spam_detected > 0 else 0
        
        return {
            "detection_rate": round(detection_rate, 2),
            "action_rate": round(action_rate, 2),
            "overall_efficiency": round((detection_rate + action_rate) / 2, 2)
        }
    
    async def save_daily_statistics(self, chat_id: int, db: Session):
        """
        Сохранить агрегированную статистику за день
        
        Args:
            chat_id: ID чата
            db: Сессия БД
        """
        try:
            today = datetime.now().date()
            
            # Проверяем, есть ли уже запись за сегодня
            existing = db.query(Statistic).filter(
                Statistic.chat_id == chat_id,
                func.date(Statistic.date) == today
            ).first()
            
            if existing:
                self.logger.info(f"Статистика за {today} для чата {chat_id} уже существует")
                return
            
            # Получаем статистику за сегодня
            start_of_day = datetime.combine(today, datetime.min.time())
            end_of_day = datetime.combine(today, datetime.max.time())
            
            total_messages = db.query(MessageLog).filter(
                MessageLog.chat_id == chat_id,
                MessageLog.created_at >= start_of_day,
                MessageLog.created_at <= end_of_day
            ).count()
            
            total_spam = db.query(MessageLog).filter(
                MessageLog.chat_id == chat_id,
                MessageLog.created_at >= start_of_day,
                MessageLog.created_at <= end_of_day,
                MessageLog.is_spam == True
            ).count()
            
            total_warnings = db.query(Warning).filter(
                Warning.chat_id == chat_id,
                Warning.issued_at >= start_of_day,
                Warning.issued_at <= end_of_day
            ).count()
            
            total_bans = db.query(Ban).filter(
                Ban.chat_id == chat_id,
                Ban.issued_at >= start_of_day,
                Ban.issued_at <= end_of_day,
                Ban.action.in_(["ban", "mute"])
            ).count()
            
            # Сохраняем статистику
            statistic = Statistic(
                chat_id=chat_id,
                date=datetime.now(),
                total_messages=total_messages,
                total_spam=total_spam,
                total_warnings=total_warnings,
                total_bans=total_bans
            )
            
            db.add(statistic)
            db.commit()
            
            self.logger.info(f"Сохранена дневная статистика для чата {chat_id}: {total_messages} сообщений, {total_spam} спама")
            
        except Exception as e:
            self.logger.error(f"Ошибка при сохранении дневной статистики: {e}")
            db.rollback()
            raise
    
    def format_statistics_text(self, stats: Dict[str, Any]) -> str:
        """
        Форматирование статистики для вывода пользователю
        
        Args:
            stats: Словарь со статистикой
            
        Returns:
            Отформатированная строка
        """
        text = f"""📊 **Статистика работы бота**

📅 **Период**: {stats['period_days']} дн. ({stats['start_date']} - {stats['end_date']})

📈 **Основные показатели**:
• Всего сообщений: {stats['total_messages']:,}
• Обнаружено спама: {stats['total_spam']:,} ({stats['spam_percentage']}%)
• Выдано предупреждений: {stats['total_warnings']:,}
• Заблокировано пользователей: {stats['total_bans']:,}

🤖 **Детекторы**:
• ML-классификатор: {stats['detector_stats']['BayesClassifier']} срабатываний
• Проверка ссылок: {stats['detector_stats']['LinkSpamDetector']} срабатываний

⚡️ **Эффективность модерации**:
• Скорость обнаружения: {stats['moderation_efficiency']['detection_rate']}%
• Скорость реагирования: {stats['moderation_efficiency']['action_rate']}%
• Общая эффективность: {stats['moderation_efficiency']['overall_efficiency']}%"""

        # Добавляем топ нарушителей если есть
        if stats['top_violators']:
            text += "\\n\\n🚫 **Топ нарушителей**:\\n"
            for i, violator in enumerate(stats['top_violators'][:3], 1):
                text += f"{i}. ID {violator['user_id']}: {violator['warning_count']} предупреждений\\n"
        
        return text
#!/usr/bin/env python3

from app.database import SessionLocal
from app.models.profanity_word import ProfanityWord

def fill_profanity_table(file_path):
    session = SessionLocal()
    
    try:
        # Читаем все слова
        with open(file_path, 'r', encoding='utf-8') as file:
            words = [line.strip() for line in file if line.strip()]
        
        # Убираем дубликаты ИЗ ФАЙЛА
        unique_words = list(set(words))
        
        print(f"📄 Всего строк в файле: {len(words)}")
        print(f"🔍 Уникальных слов: {len(unique_words)}")
        print(f"⚠️  Дубликатов в файле: {len(words) - len(unique_words)}")
        
        # Получаем уже существующие слова в БД
        existing_words = {w[0] for w in session.query(ProfanityWord.word).all()}
        
        print(f"💾 Уже в базе: {len(existing_words)} слов")
        
        # Фильтруем новые слова
        new_words = [w for w in unique_words if w not in existing_words]
        
        if new_words:
            # Bulk insert
            session.bulk_insert_mappings(
                ProfanityWord,
                [{'word': word} for word in new_words]
            )
            session.commit()
            print(f"✅ Добавлено {len(new_words)} новых слов")
        else:
            print("ℹ️  Все слова уже есть в базе данных")
        
        # Финальная статистика
        total_in_db = session.query(ProfanityWord).count()
        print(f"📊 Итого слов в базе: {total_in_db}")
        
    except Exception as e:
        session.rollback()
        print(f"❌ Ошибка при добавлении: {e}")
        raise
    finally:
        session.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python fill_profanity.py <path_to_words_file>")
        print("Example: python fill_profanity.py ru_curse_words.txt")
        sys.exit(1)
    
    file_path = sys.argv[1]
    fill_profanity_table(file_path)

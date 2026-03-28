import json
import logging
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
FAVORITES_FILE = DATA_DIR / "favorites.json"


class FavoritesManager:
    """Manage user APOD favorites locally."""

    def __init__(self):
        """Initialize data directory and load existing favorites."""
        DATA_DIR.mkdir(exist_ok=True)
        self.favorites = self._load_favorites()

    def _load_favorites(self) -> Dict[int, List[Dict]]:
        """Load favorites from JSON file."""
        if FAVORITES_FILE.exists():
            try:
                with open(FAVORITES_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading favorites: {e}")
                return {}
        return {}

    def _save_favorites(self) -> None:
        """Save favorites to JSON file."""
        try:
            with open(FAVORITES_FILE, 'w') as f:
                json.dump(self.favorites, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving favorites: {e}")

    def add_favorite(self, user_id: int, apod_data: Dict) -> bool:
        """
        Add APOD to user's favorites.

        Args:
            user_id: Discord user ID
            apod_data: APOD dict with keys: title, date, url, explanation

        Returns:
            True if added, False if already exists
        """
        user_id_str = str(user_id)

        if user_id_str not in self.favorites:
            self.favorites[user_id_str] = []

        # Check if already favourited
        for fav in self.favorites[user_id_str]:
            if fav.get('date') == apod_data.get('date'):
                logger.info(f"APOD {apod_data.get('date')} already favorited by {user_id}")
                return False

        # Add with timestamp
        fav_entry = {
            'title': apod_data.get('title'),
            'date': apod_data.get('date'),
            'url': apod_data.get('url'),
            'explanation': apod_data.get('explanation'),
            'favorited_at': datetime.now().isoformat()
        }

        self.favorites[user_id_str].append(fav_entry)
        self._save_favorites()
        logger.info(f"Added favorite for user {user_id}: {apod_data.get('title')}")
        return True

    def remove_favorite(self, user_id: int, date: str) -> bool:
        """
        Remove APOD from user's favorites.

        Args:
            user_id: Discord user ID
            date: APOD date (YYYY-MM-DD)

        Returns:
            True if removed, False if not found
        """
        user_id_str = str(user_id)

        if user_id_str not in self.favorites:
            return False

        original_count = len(self.favorites[user_id_str])
        self.favorites[user_id_str] = [
            fav for fav in self.favorites[user_id_str]
            if fav.get('date') != date
        ]

        removed = len(self.favorites[user_id_str]) < original_count

        if removed:
            self._save_favorites()
            logger.info(f"Removed favorite for user {user_id}: {date}")

        return removed

    def get_favorites(self, user_id: int) -> List[Dict]:
        """Get all favorites for a user."""
        return self.favorites.get(str(user_id), [])

    def clear_favorites(self, user_id: int) -> int:
        """
        Clear all favorites for a user.

        Returns:
            Number of favorites removed
        """
        user_id_str = str(user_id)
        count = len(self.favorites.get(user_id_str, []))

        if user_id_str in self.favorites:
            del self.favorites[user_id_str]
            self._save_favorites()
            logger.info(f"Cleared {count} favorites for user {user_id}")

        return count

    def stats(self) -> Dict:
        """Get stats about all favorites."""
        total_users = len(self.favorites)
        total_favorites = sum(len(favs) for favs in self.favorites.values())

        return {
            'total_users': total_users,
            'total_favorites': total_favorites,
            'avg_per_user': total_favorites / total_users if total_users > 0 else 0
        }


# Initialize global manager
favorites_manager = FavoritesManager()
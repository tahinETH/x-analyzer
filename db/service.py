import time
import asyncio
from typing import Dict, Optional, List, Tuple
import logging
from db.users.repository import UserRepository
from db.tw.repository import TweetDataRepository
from db.tw.structured import TweetStructuredRepository
from db.tw.accounts import AccountRepository
from ai.analyze import AIAnalyzer
from monitor import TweetMonitor
from datetime import datetime
import sqlite3
import os

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH")
SOCIAL_DATA_API_KEY = os.getenv("SOCIAL_DATA_API_KEY")
INTERVAL_MINUTES = 5
conn = sqlite3.connect(DB_PATH)





class SubscriptionTier:
    def __init__(self, tier_id: str, max_accounts: int, max_tweets: int):
        self.tier_id = tier_id
        self.max_accounts = max_accounts
        self.max_tweets = max_tweets

class SubscriptionTiers:
    FREE = SubscriptionTier('free', 0, 1)
    PREMIUM = SubscriptionTier('paid', 1, 3)

    @classmethod
    def get_tier(cls, tier_id: str) -> Optional[SubscriptionTier]:
        return getattr(cls, tier_id.upper(), cls.FREE)

class Service:
    def __init__(self):
        self.user_repository = UserRepository(conn)
        self.monitor = TweetMonitor(DB_PATH, SOCIAL_DATA_API_KEY, INTERVAL_MINUTES)
        self.data = TweetDataRepository(conn)
        self.analysis = TweetStructuredRepository(conn)
        self.accounts = AccountRepository(conn)
        self.ai_analyzer = AIAnalyzer(self.analysis)

    def _get_user_limits(self, user_id: str) -> Tuple[int, int]:
        """Get user's max allowed accounts and tweets based on their tier"""
        user = self.user_repository.get_user(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")
            
        tier = SubscriptionTiers.get_tier(user['current_tier'])
        return tier.max_accounts, tier.max_tweets

    def get_user(self, user_id: str) -> Dict:
        """Get user details"""
        user = self.user_repository.get_user(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")
        return user

    def _can_track_account(self, user_id: str) -> bool:
        """Check if user can track another account based on their tier limits"""
        try:
            max_accounts, _ = self._get_user_limits(user_id)
            tracked_items = self.user_repository.get_tracked_items(user_id)
            current_accounts = len(tracked_items['accounts'])
            
            return current_accounts < max_accounts
            
        except Exception as e:
            logger.error(f"Error checking account tracking limit for user {user_id}: {str(e)}")
            raise

    def _can_track_tweet(self, user_id: str) -> bool:
        """Check if user can track another tweet based on their tier limits"""
        try:
            _, max_tweets = self._get_user_limits(user_id)
            tracked_items = self.user_repository.get_tracked_items(user_id)
            current_tweets = len(tracked_items['tweets'])
            
            return current_tweets < max_tweets
            
        except Exception as e:
            logger.error(f"Error checking tweet tracking limit for user {user_id}: {str(e)}")
            raise

    async def handle_account_monitoring(self, user_id: str, account_identifier: str, action: str) -> bool:
        """Handle starting or stopping monitoring of an account"""
        try:
            if action == "start":
                if not self._can_track_account(user_id):
                    raise ValueError("Account tracking limit reached for user's tier")

                # Start monitoring the account
                success = await self.monitor.monitor_account(account_identifier)
                
                if success:
                    # Add to user's tracked items
                    self.user_repository.add_tracked_item(user_id, "account", account_identifier)
                    logger.info(f"Started monitoring account {account_identifier} for user {user_id}")
                    return True
                return False

            elif action == "stop":
                success = self.stop_monitoring_account(user_id, account_identifier)
                if success:
                    logger.info(f"Stopped monitoring account {account_identifier} for user {user_id}")
                return success

            else:
                raise ValueError("Invalid action. Must be 'start' or 'stop'")

        except Exception as e:
            logger.error(f"Error handling account monitoring for user {user_id}: {str(e)}")
            raise
            

    async def handle_tweet_monitoring(self, user_id: str, tweet_id: str, action: str) -> bool:
        """Handle starting or stopping monitoring of a tweet"""
        try:
            if action == "start":
                if not self._can_track_tweet(user_id):
                    raise ValueError("Tweet tracking limit reached for user's tier")

                # Start monitoring the tweet
                await self.monitor.monitor_tweet(tweet_id)
                
                # Add to user's tracked items
                self.user_repository.add_tracked_item(user_id, "tweet", tweet_id)
                logger.info(f"Started monitoring tweet {tweet_id} for user {user_id}")
                return True

            elif action == "stop":
                success = self.user_repository.remove_tracked_item(user_id, "tweet", tweet_id)
                if success:
                    logger.info(f"Stopped monitoring tweet {tweet_id} for user {user_id}")
                return success

            else:
                raise ValueError("Invalid action. Must be 'start' or 'stop'")

        except Exception as e:
            logger.error(f"Error handling tweet monitoring for user {user_id}: {str(e)}")
            raise

    async def get_monitored_tweets(self) -> List[Dict]:
        """Get all monitored tweets"""
        try:
            tweets = await self.monitor.tweet_data.get_monitored_tweets()
            logger.info(f"Retrieved {len(tweets)} monitored tweets")
            return tweets
        except Exception as e:
            logger.error(f"Error getting monitored tweets: {str(e)}")
            raise

    async def get_top_tweets(self, username: str) -> List[Dict]:
        """Get latest tweets for a user"""
        try:
            tweets = await self.monitor.get_latest_user_tweets(username)
            logger.info(f"Retrieved top tweets for user {username}")
            return tweets
        except Exception as e:
            logger.error(f"Error getting top tweets for {username}: {str(e)}")
            raise
    

    async def analyze_tweet(self, tweet_id: str) -> Dict:
        """Get AI analysis for a tweet"""
        try:
            result = await self.ai_analyzer.analyze_tweet(tweet_id)
            logger.info(f"Generated AI analysis for tweet {tweet_id}")
            return result
        except Exception as e:
            logger.error(f"Error analyzing tweet {tweet_id}: {str(e)}")
            raise

    async def get_feed(self, user_id: str) -> List[Dict]:
        """Get a feed of all monitored tweets with their latest data"""
        try:
            feed = await self.analysis.get_feed(user_id)
            logger.info(f"Retrieved feed for user {user_id}")
            return feed
        except Exception as e:
            logger.error(f"Error getting feed for user {user_id}: {str(e)}")
            raise

    async def get_tweet_history(self, tweet_id: str, format: str) -> Dict:
        """Get tweet history in raw or analyzed format"""
        try:
            if format == "raw":
                history = await self.analysis.get_raw_tweet_history(tweet_id)
            else:  # format == "analyzed"
                history = await self.analysis.get_analyzed_tweet_history(tweet_id)
                
            if not history:
                logger.warning(f"Tweet history not found for {tweet_id}")
                return None
                
            logger.info(f"Retrieved {format} history for tweet {tweet_id}")
            return history
            
        except Exception as e:
            logger.error(f"Error getting {format} tweet history for {tweet_id}: {str(e)}")
            raise




        ### ADMIN FUNCTIONs ###
    async def handle_all_accounts(self, action: str) -> bool:
        """Handle starting or stopping monitoring of all accounts"""
        try:
            if action == "start":
                self.monitor.accounts.start_all_accounts()
                logger.info("Started monitoring all accounts")
                return True
            elif action == "stop":
                self.monitor.accounts.stop_all_accounts() 
                logger.info("Stopped monitoring all accounts")
                return True
            else:
                raise ValueError("Invalid action. Must be 'start' or 'stop'")
        except Exception as e:
            logger.error(f"Error handling all accounts monitoring: {str(e)}")
            raise
        
    async def handle_all_tweets(self, action: str) -> bool:
        """Handle starting or stopping monitoring of all tweets"""
        try:
            tweets = self.monitor.tweet_data.get_monitored_tweets()
            count = 0

            if action == "start":
                for tweet in tweets:
                    if not tweet['is_active']:
                        self.monitor.tweet_data.add_monitored_tweet(tweet['tweet_id'])
                        await self.monitor.monitor_tweet(tweet['tweet_id'])
                        count += 1
                logger.info(f"Started monitoring {count} inactive tweets")
                return True

            elif action == "stop":
                for tweet in tweets:
                    if tweet['is_active']:
                        self.monitor.tweet_data.stop_monitoring_tweet(tweet['tweet_id'])
                        count += 1
                logger.info(f"Stopped monitoring {count} active tweets")
                return True

            else:
                raise ValueError("Invalid action. Must be 'start-all' or 'stop-all'")

        except Exception as e:
            action_type = "starting" if action == "start-all" else "stopping"
            logger.error(f"Error {action_type} all tweet monitoring: {str(e)}")
            raise

    ## PERIODIC CHECKS ##
    async def periodic_single_tweet_check(self):
        """Periodic task to check and update tweets"""
        while True:
            try:
                logger.info(f"Running periodic tweet check at {int(time.time())}")
                await self.monitor.check_and_update_tweets()
            except Exception as e:
                logger.error(f"Error in periodic check at {int(time.time())}: {str(e)}")
            finally:
                # Run check every minute
                await asyncio.sleep(60)

    async def periodic_account_check(self):
        """Periodic task to check and update accounts"""
        while True:
            try:
                logger.info(f"Running periodic account check at {int(time.time())}")
                await self.monitor.check_and_update_accounts()
            except Exception as e:
                logger.error(f"Error in periodic check at {int(time.time())}: {str(e)}")
            finally:
                # Run check every minute
                await asyncio.sleep(60)
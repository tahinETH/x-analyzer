from datetime import datetime
import logging
import os
from fastapi import FastAPI, HTTPException, Query, Depends, Header, Path as FastAPIPath
from pathlib import Path
import asyncio
from typing import List, Dict, Any, Optional
import uvicorn
from pydantic import BaseModel
from monitor import TweetMonitor


from db.service import Service
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import time

import tracemalloc
from auth.dependencies import auth_middleware
from webhooks.clerk import router as clerk_router

tracemalloc.start()
load_dotenv()


ADMIN_SECRET = os.getenv("ADMIN_SECRET")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI()

app.include_router(clerk_router)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)





service = Service()

class TweetInput(BaseModel):
    tweet_id: str

class AccountInput(BaseModel):
    account_identifier: str  
    action: str  

@app.get("/user")
async def get_user(user_id: str = Depends(auth_middleware)):
    """Get user details"""
    try:
        user = service.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    except Exception as e:
        logger.error(f"Error getting user details at {int(time.time())}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Account endpoints
@app.post("/account/monitor/{account_identifier}")
async def monitoring_account(
    account_identifier: str, 
    action: str = Query(None, regex="^(start|stop)$"),
    user_id: str = Depends(auth_middleware)
):
    """Start or stop monitoring an account"""
    try:
        success = await service.handle_account_monitoring(user_id, account_identifier, action)
        if success:
            return {"status": "success", "message": f"{action.title()}ed monitoring account {account_identifier}"}
        else:
            raise HTTPException(status_code=500, detail=f"Failed to {action} monitoring account")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error monitoring account at {int(time.time())}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Tweet endpoints
@app.get("/tweets")
async def get_monitored_tweets(user_id: str = Depends(auth_middleware)):
    try:
        tweets = service.get_monitored_tweets()
        logger.info(f"Retrieved {len(tweets)} monitored tweets at {int(time.time())}")
        return tweets
    except Exception as e:
        logger.error(f"Error getting monitored tweets at {int(time.time())}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/tweet/monitor/{tweet_id}")
async def monitoring_tweet(
    tweet_id: str, 
    action: str = Query(..., regex="^(start|stop)$"),
    user_id: str = Depends(auth_middleware)
):
    try:
        
        success = await service.handle_tweet_monitoring(user_id, tweet_id, action)
        if success:
            return {"status": "success", "message": f"{action.title()}ed monitoring tweet {tweet_id}"}
        else:
            raise HTTPException(status_code=500, detail=f"Failed to {action} monitoring tweet")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in tweet monitoring action at {int(time.time())}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))




@app.get("/tweet/analyze/{tweet_id}")
async def analyze_tweet(tweet_id: str, user_id: str = Depends(auth_middleware)):
    """Analyze a tweet"""
    try:
        result = await service.analyze_tweet(tweet_id)
        return result
    except Exception as e:
        logger.error(f"Error analyzing tweet {tweet_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tweet/feed")
async def get_tweet_feed(user_id: Optional[str] = None, auth_user: str = Depends(auth_middleware)):
    """Get a feed of all monitored tweets with their latest data"""
    try:
        feed = await service.get_user_feed(auth_user)
        
        return {
            "status": "success",
            "count": len(feed),
            "feed": feed
        }
    except Exception as e:
        logger.error(f"Error getting tweet feed at {int(time.time())}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving tweet feed")


@app.get("/tweet/{tweet_id}/history")
async def get_tweet_history(
    tweet_id: str, 
    format: str = Query(..., regex="^(raw|analyzed)$"),
    user_id: str = Depends(auth_middleware)
):
    """Get tweet history in raw or analyzed format"""
    try:
        history = await service.get_tweet_history(tweet_id, format)
        if not history:
            raise HTTPException(status_code=404, detail="Tweet not found")
        return history
    except Exception as e:
        logger.error(f"Error getting tweet history at {int(time.time())}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))





@app.post("/admin/account/monitor/all-accounts")
async def manage_all_accounts(action: str = Query(..., regex="^(start|stop)$"), admin_secret: str = Header(None)):
    if not admin_secret or admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Invalid admin secret")
    try:
        success = await service.handle_all_accounts(action)
        if success:
            return {"status": "success", "message": f"{action.title()}ed monitoring all accounts"}
        raise HTTPException(status_code=500, detail=f"Failed to {action} monitoring all accounts")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error {action}ing all account monitoring at {int(time.time())}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
    
@app.post("/admin/tweets/{action}")
async def handle_all_tweets(
    action: str = FastAPIPath(..., regex="^(start|stop)$"),
    admin_secret: str = Header(None)
):
    if not admin_secret or admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Invalid admin secret")
    try:
        success = await service.handle_all_tweets(action)
        if success:
            return {"status": "success", "message": f"Successfully {action}ed tweets"}
        raise HTTPException(status_code=500, detail=f"Failed to {action} tweets")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error handling all tweets at {int(time.time())}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Background tasks


@app.on_event("startup")
async def startup_event():
    """Start the periodic check on startup"""
    logger.info(f"Starting tweet monitoring background task at {int(time.time())}")
    asyncio.create_task(service.handle_periodic_checks())
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3001)
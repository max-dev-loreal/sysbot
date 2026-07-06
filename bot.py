import asyncio
import os
import subprocess

from anthropic import AsyncAnthropic
from telegram import Update 
from telegram.ext import Application, ContexTypes, MessageHandler, filters

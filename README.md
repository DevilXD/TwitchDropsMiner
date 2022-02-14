# Twitch Drops Miner

This application allows you to AFK mine timed Twitch drops, without having to worry about switching channels when the one you were watching goes offline, claiming the drops, or even receiving the stream data itself. This helps both you and Twitch save on bandwidth and hassle. Everybody wins!

**How It Works:**

Every ~60 seconds, the application sends a "minute watched" event to the channel that's currently being watched - this is enough to advance the drops. Note that this completely bypasses the need to download any actual stream video and sound. To keep the status (ONLINE or OFFLINE) of the channels up-to-date, there's a websocket connection estabilished that receives events about streams going up or down, or updates regarding the current amount of viewers.

**Features:**

- Stream-less drop mining - save on bandwidth.
- Sharded websocket connection, allowing for tracking up to `8*50-2=398` channels at the same time.
- Automatic drop campaigns discovery based on linked accounts (requires you to do [account linking](https://www.twitch.tv/drops/campaigns) yourself though)
- Stream tags and drop campaign validation, so you don't end up watching a stream that can't earn you the drop.
- Channel stream switching, when the one you were currently watching goes offline.
- Cookie saving between sessions, so you don't need to login every time.
- Mining is stopped automatically when the last available drop has been mined.

**Usage:**

- Download the [lastest release](https://github.com/DevilXD/TwitchDropsMiner/releases) - it's recommended to keep it in the folder it comes with.
- Run it and login into your Twitch using your username and password, and a 2FA key if you have one setup.
- After a successful login, the app should fetch a list of all available campaigns and games you can mine drops for - you can then select a game to have it fetch a list of all applicable streams it can watch, and start mining right away. You can also switch to a different channel as needed.
- Persistent cookies will be stored in the `cookies.jar` file, from which the authorization information will be restored on each subsequent run.

**Notes:**

- Make sure to keep your cookies file safe, as the authorization information it stores can give another person access to your Twitch account.
- Successfully logging into your Twitch account in the application, may cause Twitch to send you a "New Login" notification email. This is normal - you can verify that it comes from your own IP address. The application uses Chrome's user agent, so the detected browser during the login should signify that as well.
- The time remaining timer always countdowns a single minute and then stops - it is then restarted only after the application redetermines the remaining time. This "redetermination" can happen as early as at 10 seconds in a minute remaining, and as late as 20 seconds after the timer reaches zero (especially when finishing mining a drop), but is generally only an approximation and does not represent nor affect actual mining speed. The time variations are due to Twitch sometimes not reporting drop progress at all, or reporting progress for the wrong drop - these cases have all been accounted for in the application though.

**Troubleshooting:**

### "No active campaigns to mine drops for." or the game you're interested in is missing from the Game Selector

- Check your [inventory page](https://www.twitch.tv/drops/inventory) for in-progress campaigns - make sure you're not looking at upcoming campaigns. You can check when a campaign starts by hovering over the very first drop in the campaign.
- Make sure to link your account on the [campaigns page](https://www.twitch.tv/drops/campaigns), to the campaign's game of choice.
- Once properly linked, the game should become available in the application's Game Selector.

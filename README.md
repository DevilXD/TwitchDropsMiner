# Twitch Drops Miner

This application allows you to AFK mine timed Twitch drops, without having to worry about switching channels when the one you were watching goes offline, claiming the drops, or even receiving the stream data itself. This helps both you and Twitch save on bandwidth and hassle. Everyone wins!

### How It Works:

Every ~60 seconds, the application sends a "minute watched" event to the channel that's currently being watched - this is enough to advance the drops. Note that this completely bypasses the need to download any actual stream video and sound. To keep the status (ONLINE or OFFLINE) of the channels up-to-date, there's a websocket connection estabilished that receives events about streams going up or down, or updates regarding the current amount of viewers.

### Features:

- Stream-less drop mining - save on bandwidth.
- Game priority and exclusion lists, allowing you to focus on mining what you want, in the order you want, and ignore what you don't want.
- Sharded websocket connection, allowing for tracking up to `8*25-2=199` channels at the same time.
- Automatic drop campaigns discovery based on linked accounts (requires you to do [account linking](https://www.twitch.tv/drops/campaigns) yourself though)
- Stream tags and drop campaign validation, to ensure you won't end up mining a stream that can't earn you the drop.
- Automatic channel stream switching, when the one you were currently watching goes offline, as well as when a channel streaming a higher priority game goes online.
- Login session is saved in a cookies file, so you don't need to login every time.
- Mining is automatically started as new campaigns appear, and stopped when the last available drops have been mined.

### Usage:

- Download and unzip [the lastest release](https://github.com/DevilXD/TwitchDropsMiner/releases) - it's recommended to keep it in the folder it comes in.
- Run it and login into your Twitch account using your username and password, and a 2FA key if you have one setup. It's recommended to avoid having to double-take this step, as you can run into CAPTCHA that will prevent you from trying to log in again for the next 12+ hours. You can retry afterwards though.
- After a successful login, the app should fetch a list of all available campaigns and games you can mine drops for - you can then select and add games of choice to the Priority List available on the Settings tab, and then press on the `Reload` button to start processing. It will fetch a list of all applicable streams it can watch, and start mining right away. You can also manually switch to a different channel as needed.
- Make sure to link your Twitch account to game accounts on the [campaigns page](https://www.twitch.tv/drops/campaigns), to enable more games to be mined.
- Persistent cookies will be stored in the `cookies.jar` file, from which the authorization (login) information will be restored on each subsequent run.

#### Running on server without GUI:

- Add the argument `--cli` to launch in the Command Line Interface mode.
- To log in, you should open a link shown in the message, and enter the shown code on the webpage.
- Only necessary information is displayed, and all settings are configured in `settings.json`.

### Pictures:

![Main](https://user-images.githubusercontent.com/4180725/164298155-c0880ad7-6423-4419-8d73-f3c053730a1b.png)
![Inventory](https://user-images.githubusercontent.com/4180725/164298315-81cae0d2-24a4-4822-a056-154fd763c284.png)
![Settings](https://user-images.githubusercontent.com/4180725/164298391-b13ad40d-3881-436c-8d4c-34e2bbe33a78.png)

### Notes:

- Make sure to keep your cookies file safe, as the authorization information it stores can give another person access to your Twitch account.
- Successfully logging into your Twitch account in the application, may cause Twitch to send you a "New Login" notification email. This is normal - you can verify that it comes from your own IP address. The application uses the Twitch's SmartTV account linking process, so the detected browser during the login should signify that as well.
- The time remaining timer always countdowns a single minute and then stops - it is then restarted only after the application redetermines the remaining time. This "redetermination" can happen as early as at 10 seconds in a minute remaining, and as late as 20 seconds after the timer reaches zero (especially when finishing mining a drop), but is generally only an approximation and does not represent nor affect actual mining speed. The time variations are due to Twitch sometimes not reporting drop progress at all, or reporting progress for the wrong drop - these cases have all been accounted for in the application though.

### Support

<div align="center">

[![Buy me a coffee](https://i.imgur.com/cL95gzE.png)](
    https://www.buymeacoffee.com/DevilXD
)
[![Support me on Patreon](https://i.imgur.com/Mdkb9jq.png)](
    https://www.patreon.com/bePatron?u=26937862
)

</div>

### Advanced Usage:

If you'd be interested in running the latest master from source or building your own executable, see the wiki page explaining how to do so: https://github.com/DevilXD/TwitchDropsMiner/wiki/Setting-up-the-environment,-building-and-running

### Project goals:

Twitch Drops Miner (TDM for short) has been designed with a couple of simple goals in mind. These are, specifically:

- Twitch Drops oriented - it's in the name. That's what I made it for.
- Easy to use for an average person. Includes a nice looking GUI and is packaged as a ready-to-go executable, without requiring an existing Python installation to work.
- Intended as a helper tool that starts together with your PC, runs in the background through out the day, and then closes together with your PC shutting down at the end of the day. If it can run continously for 24 hours at minimum, and not run into any errors, I'd call that good enough already.
- Requiring a minimum amount of attention during operation - check it once or twice through out the day to see if everything's fine with it.
- Underlying service friendly - the amount of interactions done with the Twitch site is kept to the minimum required for reliable operation, at a level achievable by a diligent site user.

TDM is not intended for/as:

- Mining channel points - again, it's about the drops: only. The current points you're getting are a byproduct of getting the drops, not the main goal of it.
- Mining anything else besides Twitch drops - no, I won't be adding support for a random 3rd party site that also happens to rely on watching Twitch streams.
- Unattended operation: worst case scenario, it'll stop working and you'll hopefully notice that at some point. Hopefully.
- 100% uptime application, due to the underlaying nature of it, expect fatal errors to happen every so often.
- Being hosted on a remote server as a 24/7 miner.
- Being used with more than one managed account.
- Mining campaigns the managed account isn't linked to.

This means that features such as:

- It being possible to run it without a GUI, or with only a console attached.
- Any form of automatic restart when an error happens.
- Docker or any other form of remote deployment.
- Using it with more than one managed account.
- Making it possible to mine campaigns that the managed account isn't linked to.
- Anything that increases the site processing load caused by the application.
- Any form of additional notifications system (email, webhook, etc.), beyond what's already implemented.

..., are most likely not going to be a feature, ever. You're welcome to search through the existing issues to comment on your point of view on the relevant matters, where applicable. Otherwise, most of the new issues that go against these goals will be closed and the user will be pointed to this paragraph.

For more context about these goals, please check out these issues: [#161](https://github.com/DevilXD/TwitchDropsMiner/issues/161), [#105](https://github.com/DevilXD/TwitchDropsMiner/issues/105), [#84](https://github.com/DevilXD/TwitchDropsMiner/issues/84)

### Credits:

<!---
Note: When adding a new credits line below, please add two spaces at the end of the previous line,
if they aren't already there. Doing so ensures proper markdown rendering on Github.

• Last line can have them omitted.
• Please ensure your editor won't trim the spaces upon saving the file.
• Please leave a single empty new line at the end of the file.
-->

@Suz1e - For the entirety of the Chinese (简体中文) translation and revisions.  
@wwj010 - For the Chinese (简体中文) translation corrections and revisions.  
@nwvh - For the entirety of the Czech (Čeština) translation.  
@ThisIsCyreX - For the entirety of the German (Deutsch) translation.  
@Shofuu - For the entirety of the Spanish (Español) translation.  
@zarigata - For the entirety of the Portuguese (Português) translation.  
@alikdb - For the entirety of the Turkish (Türkçe) translation.  
@roobini-gamer - For the entirety of the French (Français) translation.  
@Sergo1217 - For the entirety of the Russian (Русский) translation.  
@Ricky103403 - For the entirety of the Traditional Chinese (繁體中文) translation.  
@Patriot99 - For the Polish (Polski) translation (co-authored with @DevilXD).

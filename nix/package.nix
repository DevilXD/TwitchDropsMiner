{
  lib,
  python3Packages,
  wrapGAppsHook3,
  gobject-introspection,
  gtk3,
  libnotify,
  copyDesktopItems,
  makeDesktopItem,
}:

python3Packages.buildPythonApplication rec {
  pname = "twitch-drops-miner";
  version = "15-dev";

  # Use the local repository as the source
  src = ../.;

  format = "other";

  nativeBuildInputs = [
    wrapGAppsHook3
    gobject-introspection
    copyDesktopItems
  ];

  buildInputs = [
    gtk3
    libnotify
  ];

  propagatedBuildInputs = with python3Packages; [
    aiohttp
    pillow
    pystray
    pygobject3
    truststore
    tkinter
  ];

  dontWrapGApps = true;

  # Patch the immutable path behavior for Linux
  postPatch = ''
    substituteInPlace constants.py \
      --replace-fail 'IS_PACKAGED = hasattr(sys, "_MEIPASS") or IS_APPIMAGE' 'IS_PACKAGED = True' \
      --replace-fail 'WORKING_DIR = SELF_PATH.parent' 'import os; WORKING_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"), "twitch-drops-miner"); WORKING_DIR.mkdir(parents=True, exist_ok=True)'
    substituteInPlace utils.py \
      --replace-fail 'if IS_PACKAGED and sys.platform == "linux":' 'if False:'
  '';

  desktopItems = [
    (makeDesktopItem {
      name = "twitch-drops-miner";
      exec = "twitch-drops-miner";
      icon = "twitch-drops-miner";
      desktopName = "Twitch Drops Miner";
      comment = "An app that allows you to AFK mine Twitch drops";
      categories = [
        "Utility"
        "Network"
        "Game"
      ];
    })
  ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/share/twitch-drops-miner
    cp -r * $out/share/twitch-drops-miner/

    # Install icon
    install -Dm644 appimage/pickaxe.png $out/share/icons/hicolor/256x256/apps/twitch-drops-miner.png

    # Create the executable wrapper
    mkdir -p $out/bin
    cat > $out/bin/twitch-drops-miner <<EOF
    #!${python3Packages.python.interpreter}
    import sys
    import runpy

    # Add the share directory to the path so it can find its modules
    sys.path.insert(0, "$out/share/twitch-drops-miner")
    sys._MEIPASS = "$out/share/twitch-drops-miner"

    if __name__ == "__main__":
        runpy.run_path("$out/share/twitch-drops-miner/main.py", run_name="__main__")
    EOF
    chmod +x $out/bin/twitch-drops-miner

    runHook postInstall
  '';

  preFixup = ''
    makeWrapperArgs+=("''${gappsWrapperArgs[@]}")
  '';

  meta = with lib; {
    description = "An app that allows you to AFK mine Twitch drops, without having to worry about switching channels or claiming drops";
    homepage = "https://github.com/DevilXD/TwitchDropsMiner";
    license = licenses.gpl3Only;
    maintainers = [ ];
    mainProgram = "twitch-drops-miner";
    platforms = platforms.linux;
  };
}

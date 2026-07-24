{
  description = "An app that allows you to AFK mine Twitch drops, without having to worry about switching channels or claiming drops";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      pkgsFor = system: nixpkgs.legacyPackages.${system};
    in
    {
      packages = forAllSystems (system: {
        default = (pkgsFor system).callPackage ./nix/package.nix { };
        twitch-drops-miner = (pkgsFor system).callPackage ./nix/package.nix { };
      });

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/twitch-drops-miner";
        };
        twitch-drops-miner = {
          type = "app";
          program = "${self.packages.${system}.twitch-drops-miner}/bin/twitch-drops-miner";
        };
      });

      devShells = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
        in
        {
          default = pkgs.mkShell {
            inputsFrom = [ self.packages.${system}.default ];

            packages = with pkgs; [
              python3Packages.pytest
              python3Packages.black
            ];
          };
        }
      );
    };
}

{
  description = "One flake to rule them all";

  inputs = {
    nixpkgs = {
      type = "github";
      owner = "nixos";
      repo = "nixpkgs";
      ref = "nixos-unstable";
    };
  };

  outputs =
    {
      nixpkgs,
      ...
    }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;

        config = {
          allowUnfree = true;
          permittedInsecurePackages = [
            "segger-jlink-qt4-810"
          ];
          segger-jlink.acceptLicense = true;
        };
      };

      inherit (pkgs) mkShell;
    in
    {
      devShells.${system}.default = mkShell {
        name = "cli-background-server";
        packages = with pkgs; [
          basedpyright
          just
          jq
          python312Packages.greenlet
          ruff
          uv
        ];
      };
    };
}

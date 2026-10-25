{ lib, python3Packages }:
python3Packages.buildPythonApplication {
  pname = "orgm-multimedia";
  version = "0.1.0";
  pyproject = true;
  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [ ./pyproject.toml ./orgm_home ./tests ];
  };
  build-system = [ python3Packages.setuptools ];
  dependencies = with python3Packages; [ fastapi uvicorn jinja2 pyjwt cryptography ];
  nativeCheckInputs = with python3Packages; [ pytestCheckHook httpx ];
  pythonImportsCheck = [ "orgm_home.web" "orgm_home.agent" ];
  meta = {
    description = "ORGM Home multimedia session controller and responsive remote";
    mainProgram = "orgm-home";
    platforms = lib.platforms.linux;
  };
}

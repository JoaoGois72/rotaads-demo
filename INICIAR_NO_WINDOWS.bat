@echo off
setlocal
cd /d "%~dp0"
title RotaAds V1.4 - Teste no computador

echo ===========================================================
echo    ROTAADS V1.4 - TESTE LOCAL NO WINDOWS
echo ===========================================================
echo.
if not exist "instance\rotaads.sqlite3" (
  echo ERRO: Banco V1.4 nao encontrado. Antes, execute migrar_da_v1_3_1.py conforme README.md!
  pause
  exit /b 1
)
where py >nul 2>&1
if errorlevel 1 (
  echo ERRO: Python nao foi encontrado.
  echo Instale Python 3.11 ou superior e selecione Add Python to PATH.
  echo Depois execute este ficheiro novamente.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo [1/4] A preparar o ambiente Python...
  py -3 -m venv .venv
  if errorlevel 1 goto :ERRO
) else (
  echo [1/4] Ambiente Python encontrado.
)

echo [2/4] A instalar as dependencias (necessita de internet)...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :ERRO

echo [3/4] A verificar a configuracao local...
".venv\Scripts\python.exe" configurar_windows.py
if errorlevel 1 goto :ERRO

echo [4/4] A executar os testes automaticos...
".venv\Scripts\python.exe" testes_v1_0.py
if errorlevel 1 goto :ERRO
".venv\Scripts\python.exe" testes_v1_1.py
if errorlevel 1 goto :ERRO
".venv\Scripts\python.exe" testes_v1_2.py
if errorlevel 1 goto :ERRO
".venv\Scripts\python.exe" testes_v1_3.py
if errorlevel 1 goto :ERRO
".venv\Scripts\python.exe" testes_v1_3_1.py
if errorlevel 1 goto :ERRO
".venv\Scripts\python.exe" testes_v1_3_1_flask.py
if errorlevel 1 goto :ERRO
".venv\Scripts\python.exe" testes_correcao_pdf_v131.py
if errorlevel 1 goto :ERRO
".venv\Scripts\python.exe" testes_v1_4.py
if errorlevel 1 (
  echo.
  echo OS TESTES INDICARAM UM ERRO. Nao iniciar ate corrigir.
  pause
  exit /b 1
)

echo.
echo ===========================================================
echo TESTES OK. O site sera iniciado neste computador.
echo Pagina: http://127.0.0.1:5000
echo Gestao: http://127.0.0.1:5000/admin/entrar
echo Frotas: http://127.0.0.1:5000/admin/frotas
echo Pagamentos: http://127.0.0.1:5000/admin/pagamentos
echo Portal: http://127.0.0.1:5000/anunciante/entrar
echo Para terminar, prima CTRL+C nesta janela.
echo ===========================================================
echo.
".venv\Scripts\python.exe" app.py
pause
exit /b 0

:ERRO
echo.
echo Nao foi possivel preparar o sistema.
echo Copie a mensagem de erro e envie-a para avaliarmos.
pause
exit /b 1

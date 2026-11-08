# Consumo del orbe 3D en la ventana real: GPU y CPU de los procesos de WebView2 de Jarvis + fps que mide el orbe.
#   powershell -File pruebas\medir_orbe.ps1
# Mide en reposo (visible), hablando (voz simulada, visible) y con la ventana oculta. Deja el orbe oculto.
$url = "http://127.0.0.1:8765"
function Post($ruta, $cuerpo) { Invoke-WebRequest -UseBasicParsing -Method Post "$url$ruta" -Body $cuerpo -ContentType application/json | Out-Null }
function PidsJarvis {
  $p = (Get-NetTCPConnection -LocalPort 8765 -State Listen -EA SilentlyContinue | Select -First 1).OwningProcess
  $todos = Get-CimInstance Win32_Process | Select ProcessId, ParentProcessId
  $hijos = @($p); $nuevos = @($p)
  while ($nuevos.Count) { $nuevos = @($todos | Where-Object { $nuevos -contains $_.ParentProcessId } | ForEach-Object ProcessId); $hijos += $nuevos }
  return $hijos
}
function Medir($nombre) {
  $pids = PidsJarvis
  $gpu = (Get-Counter '\GPU Engine(*)\Utilization Percentage' -SampleInterval 2 -MaxSamples 3).CounterSamples |
    Where-Object { $i = $_.InstanceName; ($pids | Where-Object { $i -match "pid_$($_)_" }).Count -gt 0 } |
    Measure-Object CookedValue -Sum
  $cpu1 = (Get-Process -Id $pids -EA SilentlyContinue | Measure-Object CPU -Sum).Sum; Start-Sleep 3
  $cpu2 = (Get-Process -Id $pids -EA SilentlyContinue | Measure-Object CPU -Sum).Sum
  $tam = (Get-Item ..\datos\jarvis.log -EA SilentlyContinue).Length
  Invoke-WebRequest -UseBasicParsing "$url/api/diag" | Out-Null; Start-Sleep 1
  $diag = (Get-Content datos\jarvis.log -Tail 3 -Encoding UTF8 | Select-String 'DIAG' | Select -Last 1).Line
  $fps = if ($diag -match '"fps":(\d+)') { $Matches[1] } else { "?" }
  $corr = if ($diag -match '"corriendo":(true|false)') { $Matches[1] } else { "?" }
  $nucleos = (Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors
  "{0,-22} GPU {1,5:N1} %   CPU {2,5:N1} % (de todo el equipo)   fps del orbe {3}   dibujando {4}" -f $nombre, ($gpu.Sum / 3), (($cpu2 - $cpu1) / 3 * 100 / $nucleos), $fps, $corr
}
Set-Location (Split-Path $PSScriptRoot)
Post "/api/despertar" '{"mostrar":true,"activar":false}'; Post "/api/demo" '{"estado":"reposo","simular":false}'; Start-Sleep 4
Medir "reposo (visible)"
Post "/api/demo" '{"estado":"hablando","simular":true}'; Start-Sleep 3
Medir "hablando (visible)"
Post "/api/demo" '{"estado":"pensando","simular":false}'; Start-Sleep 3
Medir "pensando (visible)"
Post "/api/demo" '{"estado":"reposo","simular":false}'
Post "/api/ocultar_orbe" '{}'; Start-Sleep 3
Medir "oculto"

!define APPNAME "Ripple Charge Effect"
!define COMPANYNAME "Mr_Bocchi"
!define EXENAME "RippleChargeEffect.exe"
!define SOURCE_PATH "..\dist"
!define APPVERSION "1.0.0"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"

OutFile "RCE_Setup.exe"

InstallDir "$LOCALAPPDATA\RippleChargeEffect"
RequestExecutionLevel user

Page directory
Page instfiles

Section "Install"

    SetOutPath "$INSTDIR"

    File /r "${SOURCE_PATH}\*.*"

    CreateDirectory "$SMPROGRAMS\WaterRippleCharge"
    CreateShortcut "$SMPROGRAMS\WaterRippleCharge\${APPNAME}.lnk" "$INSTDIR\${EXENAME}"

    CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${EXENAME}"

    WriteUninstaller "$INSTDIR\Uninstall.exe"
    
    WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APPNAME}"
    WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${APPVERSION}"
    WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" "$\"$INSTDIR\Uninstall.exe$\""
    WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${EXENAME}"
    WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${COMPANYNAME}"
    
    WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
    WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"

    Delete "$DESKTOP\${APPNAME}.lnk"
    Delete "$SMPROGRAMS\WaterRippleCharge\${APPNAME}.lnk"
    RMDir "$SMPROGRAMS\WaterRippleCharge"

    DeleteRegKey HKCU "${UNINST_KEY}"

    SetOutPath "$TEMP"
    RMDir /r "$INSTDIR"

SectionEnd
let rememberedAdminPassword = "";

export function getRememberedAdminPassword() {
  return rememberedAdminPassword;
}

export function rememberAdminPassword(password: string) {
  rememberedAdminPassword = password;
}

export function forgetAdminPassword() {
  rememberedAdminPassword = "";
}

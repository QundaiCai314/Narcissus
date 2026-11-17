// Local guidance only; never send passwords away to obtain a rating.
export function passwordStrength(value: string) {
  const length = Array.from(value).length, distinct = new Set(Array.from(value)).size;
  const stem = value.toLowerCase().replace(/[^a-z]/g, "");
  const common = new Set(["password", "qwerty", "asdfgh", "zxcvbn", "narcissus", "admin", "administrator", "letmein", "welcome", "iloveyou"]);
  const sequential = ["0123456789", "9876543210", "abcdefghijklmnopqrstuvwxyz", "zyxwvutsrqponmlkjihgfedcba"].some((sequence) => sequence.repeat(14).includes(value.toLowerCase()));
  let problem = "";
  if (length < 10) problem = "至少使用 10 个字符，建议 15 位以上的长密码。";
  else if (length > 128) problem = "密码不能超过 128 个字符。";
  else if (distinct < 4 || new RegExp("^(.{1,64})\\1+$", "su").test(value) || common.has(stem) || sequential) problem = "请避开常见密码、连续字符和重复片段。";
  const score = problem ? 1 : length >= 20 && distinct >= 8 ? 4 : length >= 15 && distinct >= 6 ? 3 : 2;
  return { score, problem, label: ["", "较弱", "一般", "较好", "较强"][score], hint: problem || (score < 3 ? "建议增加长度；可以使用几个不相关词语组成的长密码。" : "长度充足，请为这个账号使用独立密码。") };
}

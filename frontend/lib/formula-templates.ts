export type FormulaTemplate = {
  id: string;
  category: string;
  label: string;
  latex: string;
};
const p = String.raw`\placeholder{}`;
const groups: [string, [string, string][]][] = [
  [
    "常用符号",
    [
      ["加减", "\\pm"],
      ["乘号", "\\times"],
      ["除号", "\\div"],
      ["不等于", "\\ne"],
      ["小于等于", "\\le"],
      ["大于等于", "\\ge"],
      ["约等于", "\\approx"],
      ["无穷", "\\infty"],
      ["属于", "\\in"],
      ["包含", "\\subseteq"],
      ["并集", "\\cup"],
      ["交集", "\\cap"],
      ["任意", "\\forall"],
      ["存在", "\\exists"],
      ["偏导符号", "\\partial"],
      ["梯度", "\\nabla"],
    ],
  ],
  [
    "希腊字母",
    [
      ["alpha", "\\alpha"],
      ["beta", "\\beta"],
      ["gamma", "\\gamma"],
      ["delta", "\\delta"],
      ["epsilon", "\\epsilon"],
      ["theta", "\\theta"],
      ["lambda", "\\lambda"],
      ["mu", "\\mu"],
      ["pi", "\\pi"],
      ["sigma", "\\sigma"],
      ["phi", "\\varphi"],
      ["omega", "\\omega"],
      ["Delta", "\\Delta"],
      ["Sigma", "\\Sigma"],
      ["Phi", "\\Phi"],
      ["Omega", "\\Omega"],
    ],
  ],
  [
    "分式",
    [
      ["上下分式", `\\frac{${p}}{${p}}`],
      ["斜线分式", `${p}/${p}`],
      ["紧凑分式", `\\tfrac{${p}}{${p}}`],
      ["连分式", `\\frac{${p}}{${p}+\\frac{${p}}{${p}}}`],
      ["偏导数", `\\frac{\\partial ${p}}{\\partial ${p}}`],
      ["微分商", `\\frac{d ${p}}{d ${p}}`],
    ],
  ],
  [
    "上下标",
    [
      ["上标", `${p}^{${p}}`],
      ["下标", `${p}_{${p}}`],
      ["上下标", `${p}_{${p}}^{${p}}`],
      ["左侧上下标", `{}_{${p}}^{${p}}${p}`],
      ["二项式系数", `\\binom{${p}}{${p}}`],
    ],
  ],
  [
    "根式",
    [
      ["平方根", `\\sqrt{${p}}`],
      ["立方根", `\\sqrt[3]{${p}}`],
      ["任意次根", `\\sqrt[${p}]{${p}}`],
    ],
  ],
  [
    "积分",
    [
      ["不定积分", `\\int ${p}\\,d${p}`],
      ["定积分", `\\int_{${p}}^{${p}} ${p}\\,d${p}`],
      ["二重积分", `\\iint_{${p}} ${p}\\,d${p}`],
      ["三重积分", `\\iiint_{${p}} ${p}\\,d${p}`],
      ["曲线积分", `\\oint_{${p}} ${p}\\,d${p}`],
    ],
  ],
  [
    "求和与乘积",
    [
      ["有限求和", `\\sum_{${p}}^{${p}} ${p}`],
      ["无穷级数", `\\sum_{n=1}^{\\infty} ${p}`],
      ["连乘", `\\prod_{${p}}^{${p}} ${p}`],
      ["大并集", `\\bigcup_{${p}}^{${p}} ${p}`],
      ["大交集", `\\bigcap_{${p}}^{${p}} ${p}`],
    ],
  ],
  [
    "极限与函数",
    [
      ["极限", `\\lim_{${p}\\to ${p}} ${p}`],
      ["最大值", `\\max_{${p}} ${p}`],
      ["最小值", `\\min_{${p}} ${p}`],
      ["正弦", `\\sin\\left(${p}\\right)`],
      ["余弦", `\\cos\\left(${p}\\right)`],
      ["正切", `\\tan\\left(${p}\\right)`],
      ["对数", `\\log_{${p}} ${p}`],
      ["自然对数", `\\ln ${p}`],
      ["指数函数", `e^{${p}}`],
    ],
  ],
  [
    "括号与分段",
    [
      ["圆括号", `\\left(${p}\\right)`],
      ["方括号", `\\left[${p}\\right]`],
      ["大括号", `\\left\\{${p}\\right\\}`],
      ["绝对值", `\\left|${p}\\right|`],
      ["范数", `\\left\\|${p}\\right\\|`],
      ["分段函数", `\\begin{cases}${p} & ${p}\\\\ ${p} & ${p}\\end{cases}`],
      ["多行推导", `\\begin{aligned}${p}&=${p}\\\\&=${p}\\end{aligned}`],
    ],
  ],
  [
    "矩阵",
    [
      ["二阶矩阵", `\\begin{pmatrix}${p}&${p}\\\\${p}&${p}\\end{pmatrix}`],
      [
        "三阶矩阵",
        `\\begin{pmatrix}${p}&${p}&${p}\\\\${p}&${p}&${p}\\\\${p}&${p}&${p}\\end{pmatrix}`,
      ],
      ["方括号矩阵", `\\begin{bmatrix}${p}&${p}\\\\${p}&${p}\\end{bmatrix}`],
      ["行列式", `\\begin{vmatrix}${p}&${p}\\\\${p}&${p}\\end{vmatrix}`],
      ["列向量", `\\begin{pmatrix}${p}\\\\${p}\\\\${p}\\end{pmatrix}`],
      ["单位矩阵", "\\begin{pmatrix}1&0&0\\\\0&1&0\\\\0&0&1\\end{pmatrix}"],
    ],
  ],
  [
    "箭头与重音",
    [
      ["向量", `\\vec{${p}}`],
      ["上横线", `\\overline{${p}}`],
      ["下横线", `\\underline{${p}}`],
      ["帽号", `\\hat{${p}}`],
      ["一阶导数点", `\\dot{${p}}`],
      ["二阶导数点", `\\ddot{${p}}`],
      ["右箭头", "\\to"],
      ["推出", "\\Rightarrow"],
      ["等价", "\\Leftrightarrow"],
      ["上括线", `\\overbrace{${p}}^{${p}}`],
      ["下括线", `\\underbrace{${p}}_{${p}}`],
    ],
  ],
];
export const formulaCategories = ["最近使用", ...groups.map(([name]) => name)];
export const formulaTemplates: FormulaTemplate[] = groups.flatMap(
  ([category, items]) =>
    items.map(([label, latex], i) => ({
      id: `${category}-${i}`,
      category,
      label,
      latex,
    })),
);
export type FormulaRange = {
  start: number;
  end: number;
  latex: string;
  display: boolean;
};
export function answerFormulas(text: string): FormulaRange[] {
  const ranges: FormulaRange[] = [];
  const pattern =
    /(?<!\\)\$\$([\s\S]*?)(?<!\\)\$\$|(?<!\\)\$([^$\n]+)(?<!\\)\$/g;
  for (const match of text.matchAll(pattern))
    ranges.push({
      start: match.index!,
      end: match.index! + match[0].length,
      latex: (match[1] ?? match[2]).trim(),
      display: match[1] !== undefined,
    });
  return ranges;
}

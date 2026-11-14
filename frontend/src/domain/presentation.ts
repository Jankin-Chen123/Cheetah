// Keep provenance on the data and exports; omit fixture annotations in the UI.
export function previewText(value: string): string {
  return value
    .replace(/\s*·\s*规则\s+v\d+(?:\.\d+)*/gi, '')
    .replace(/规则\s+v\d+(?:\.\d+)*/gi, '规则')
    .replace(/[^。\n]*(?:用于验证|不证明真实|无真实拨号|仅验证|仅供演示)[^。\n]*。?/g, '')
    .replace(/【[^】]*(?:模拟|虚构|预置)[^】]*】/g, '')
    .replace(/[（(](?:虚构(?:标准)?|模拟|仅限模拟样例)[）)]/g, '')
    .replace(/测试规则/g, '规则')
    .replace(/预置模拟访谈/g, '沟通记录')
    .replace(/虚构材料|虚构简历/g, '简历材料')
    .replace(/模拟访谈/g, '沟通记录')
    .replace(/(?:此为|这是|结论为)[^。\n]*(?:演示|预置|样例)[^。\n]*。?/g, '')
    .replace(/仅验证[^。\n]*。?/g, '')
    .replace(/未由真实模型生成。?/g, '')
    .replace(/非真实转写[，。]?/g, '')
    .replace(/模拟样例|模拟初筛|模拟提纲|模拟内部评估|模拟推荐草案|模拟研究状态/g, '')
    .replace(/模拟/g, '')
    .replace(/虚构/g, '')
    .replace(/预置/g, '')
    .replace(/演示/g, '')
    .trim()
}

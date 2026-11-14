import type { Job } from './workspace'
import type { DocumentTable, JobDocument } from './jobDocuments'
import { canExportJobDocument } from './jobDocuments'

const sourceLabel = (document: JobDocument) => document.source === 'mock' || document.inheritedSources.includes('mock') ? '模拟样例，非真实模型结果' : document.source === 'manual' ? '人工修订' : '模型生成'
const stamp = (document: JobDocument) => `v${document.version} · ${sourceLabel(document)} · ${document.status === 'confirmed' ? '已确认' : '待确认'}`
const safeName = (name: string) => Array.from(name).map(char => char.charCodeAt(0) < 32 || '<>:"/\\|?*'.includes(char) ? '_' : char).join('').slice(0, 100)
function validate(job: Job, documents: JobDocument[]) {
  if (!documents.length || documents.some(document => !canExportJobDocument(job, document))) throw new Error('只能导出当前可用内容；待复核产物请先确认。')
  for (const document of documents) {
    if (document.type === 'D02' && document.tables.find(t => t.id === 'dimensions')?.rows.some(row => row.cells[4] || row.cells[5])) throw new Error('岗位面试表不能预填候选人实际得分。')
  }
}
function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function exportJobWord(job: Job, documents: JobDocument[]) {
  validate(job, documents)
  const { AlignmentType, BorderStyle, Document, HeadingLevel, Packer, PageOrientation, Paragraph, Table, TableCell, TableRow, TextRun, VerticalAlign, WidthType } = await import('docx')
  const paragraph = (value: string, bold = false) => new Paragraph({ spacing: { after: 80, line: 280 }, children: [new TextRun({ text: value, bold, font: 'Microsoft YaHei', size: 21 })] })
  const borders = Object.fromEntries(['top', 'left', 'bottom', 'right'].map(edge => [edge, { style: BorderStyle.SINGLE, size: 4, color: 'D9D9D9' }]))
  function tableBlock(table: DocumentTable, width: number) {
    const widths = table.widths.map(part => Math.round(part * width))
    const makeRow = (cells: string[], header = false, group = false) => new TableRow({ tableHeader: header, cantSplit: header || group, children: (group ? cells.slice(0, 1) : cells).map((value, index) => new TableCell({
      width: { size: group ? width : widths[index], type: WidthType.DXA }, columnSpan: group ? table.headers.length : 1,
      verticalAlign: VerticalAlign.CENTER, margins: { top: 110, bottom: 110, left: 130, right: 130 }, borders,
      shading: { fill: header ? 'E2EADD' : group ? 'F1F5EC' : 'FFFFFF' },
      children: value.split('\n').map(line => paragraph(line, header || group)),
    })) })
    return new Table({ width: { size: width, type: WidthType.DXA }, columnWidths: widths, rows: [makeRow(table.headers, true), ...table.rows.map(row => makeRow(row.cells, false, !!row.group))] })
  }
  const sections = documents.map(document => {
    const landscape = document.type === 'D02'; const width = landscape ? 14678 : 9746
    return {
      properties: { page: { size: { orientation: landscape ? PageOrientation.LANDSCAPE : PageOrientation.PORTRAIT }, margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 } } },
      children: [new Paragraph({ text: `${job.title} ${document.title}`, heading: HeadingLevel.TITLE, alignment: AlignmentType.LEFT }), paragraph(stamp(document)), ...document.tables.flatMap(table => [
        ...(table.title ? [new Paragraph({ text: table.title, heading: HeadingLevel.HEADING_2, keepNext: true, spacing: { before: 280, after: 140 } })] : []),
        tableBlock(table, width), new Paragraph({ text: '' }),
      ]), ...(document.unknowns.length ? [paragraph('待核实事项', true), ...document.unknowns.map(value => paragraph(value))] : [])],
    }
  })
  const result = new Document({ creator: 'Cheetah', title: `${job.title} 岗位产物`, styles: { default: { document: { run: { font: 'Microsoft YaHei', size: 21, color: '222222' } }, title: { run: { color: '000000', bold: true, size: 32 }, paragraph: { spacing: { after: 180 } } }, heading2: { run: { color: '000000', bold: true, size: 24 } } } }, sections })
  download(await Packer.toBlob(result), `${safeName(job.title)}_${documents.length > 1 ? '岗位产物' : documents[0].title}.docx`)
}

// Render Chinese using the browser's installed fonts; no text is uploaded to a font or conversion service.
// The PDF is a high-resolution printable copy. The DOCX retains editable text and tables.
export async function exportJobPdf(job: Job, documents: JobDocument[]) {
  validate(job, documents)
  await document.fonts.ready
  const { jsPDF } = await import('jspdf')
  const firstLandscape = documents[0].type === 'D02'
  const pdf = new jsPDF({ orientation: firstLandscape ? 'landscape' : 'portrait', unit: 'mm', format: 'a4', compress: true })
  let pageCount = 0
  for (const artifact of documents) {
    const landscape = artifact.type === 'D02'
    const pageWidth = landscape ? 1584 : 1120; const pageHeight = landscape ? 1120 : 1584
    const canvas = document.createElement('canvas'); canvas.width = pageWidth; canvas.height = pageHeight
    const context = canvas.getContext('2d')
    if (!context) throw new Error('浏览器无法创建 PDF 画布。')
    const ctx = context; const margin = 64; const contentWidth = pageWidth - margin * 2; const lineHeight = 30; const padding = 13
    let y = 0; let hasContent = false
    const font = (bold = false, size = 21) => { ctx.font = `${bold ? '600' : '400'} ${size}px "Microsoft YaHei", "PingFang SC", sans-serif` }
    const wrap = (value: string, width: number): string[] => {
      const result: string[] = []
      for (const paragraph of value.split('\n')) {
        let current = ''
        for (const char of Array.from(paragraph)) {
          if (current && ctx.measureText(current + char).width > width) { result.push(current); current = char } else current += char
        }
        result.push(current)
      }
      return result
    }
    const startPage = () => {
      ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, pageWidth, pageHeight); ctx.textBaseline = 'top'; ctx.fillStyle = '#222222'
      font(true, 30)
      const titleLines = wrap(`${job.title} ${artifact.title}`, contentWidth)
      titleLines.forEach((line, index) => ctx.fillText(line, margin, margin + index * 40))
      y = margin + titleLines.length * 40 + 8; font(false, 17); ctx.fillStyle = '#65735d'
      ctx.fillText(stamp(artifact), margin, y); y += 45; hasContent = false
    }
    const flush = () => {
      font(false, 16); ctx.fillStyle = '#87917e'; ctx.fillText(`${artifact.title} v${artifact.version} / ${++pageCount}`, margin, pageHeight - 40)
      if (pageCount > 1) pdf.addPage('a4', landscape ? 'landscape' : 'portrait')
      pdf.addImage(canvas.toDataURL('image/jpeg', 0.95), 'JPEG', 0, 0, landscape ? 297 : 210, landscape ? 210 : 297, undefined, 'FAST')
    }
    const drawRow = (lines: string[][], widths: number[], height: number, fill: string, bold = false) => {
      let x = margin; font(bold)
      for (let index = 0; index < lines.length; index++) {
        ctx.fillStyle = fill; ctx.fillRect(x, y, widths[index], height)
        ctx.strokeStyle = '#d9d9d9'; ctx.lineWidth = 1; ctx.strokeRect(x, y, widths[index], height)
        ctx.fillStyle = '#2c3829'
        lines[index].forEach((line, n) => ctx.fillText(line, x + padding, y + padding + n * lineHeight))
        x += widths[index]
      }
      y += height; hasContent = true
    }
    startPage()
    for (const table of artifact.tables) {
      const widths = table.widths.map(part => part * contentWidth)
      font(true); const headers = table.headers.map((value, index) => wrap(value, widths[index] - padding * 2))
      const headerHeight = Math.max(...headers.map(lines => lines.length)) * lineHeight + padding * 2
      const header = () => drawRow(headers, widths, headerHeight, '#e2eadd', true)
      if (y + headerHeight + 100 > pageHeight - margin && hasContent) { flush(); startPage() }
      if (table.title) { font(true, 24); ctx.fillStyle = '#222222'; ctx.fillText(table.title, margin, y); y += 46 }
      header()
      for (const row of table.rows) {
        font(!!row.group)
        const rowWidths = row.group ? [contentWidth] : widths
        let remaining = (row.group ? row.cells.slice(0, 1) : row.cells).map((value, index) => wrap(value, rowWidths[index] - padding * 2))
        const rowHeight = Math.max(...remaining.map(lines => lines.length)) * lineHeight + padding * 2
        if (y + rowHeight > pageHeight - margin && rowHeight < pageHeight - margin * 2 - 180 - headerHeight) { flush(); startPage(); header() }
        while (remaining.some(lines => lines.length)) {
          let available = Math.floor((pageHeight - margin - y - padding * 2) / lineHeight)
          const needed = Math.max(...remaining.map(lines => lines.length))
          if (available < Math.min(needed, 3)) { flush(); startPage(); header(); available = Math.floor((pageHeight - margin - y - padding * 2) / lineHeight) }
          const take = Math.min(needed, available)
          drawRow(remaining.map(lines => lines.slice(0, take)), rowWidths, take * lineHeight + padding * 2, row.group ? '#f1f5ec' : '#ffffff', !!row.group)
          remaining = remaining.map(lines => lines.slice(take))
          if (remaining.some(lines => lines.length)) { flush(); startPage(); header() }
        }
      }
      y += 24
    }
    for (const note of artifact.unknowns) {
      font(false, 19)
      for (const line of wrap(`待核实：${note}`, contentWidth)) {
        if (y + 30 > pageHeight - margin) { flush(); startPage() }
        ctx.fillStyle = '#7d6c42'; ctx.fillText(line, margin, y); y += 30
      }
    }
    flush()
  }
  pdf.save(`${safeName(job.title)}_${documents.length > 1 ? '岗位产物' : documents[0].title}.pdf`)
}

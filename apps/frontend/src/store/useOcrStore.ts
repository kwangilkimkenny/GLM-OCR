import { create } from 'zustand'

export interface Block {
	id: number
	content: string
	bbox: [number, number, number, number] | null
	pageIndex: number
	isImage?: boolean
	width: number
	height: number
}

// 추출 필드 hover 시 원본 이미지에 강조할 박스 (layout block 과 별개 색상)
export interface FieldHighlight {
	fieldName: string
	label: string
	value: string
	bbox: [number, number, number, number]
	pageIndex: number
}

// ROI(사용자 지정 영역) — 양식 손글씨 등을 영역별로 OCR
export interface Roi {
	id: string
	name: string
	bbox: [number, number, number, number]  // 원본 픽셀 좌표
	text?: string
	processingTimeMs?: number
	status: 'idle' | 'running' | 'done' | 'error'
	error?: string
}

// HITL — Human-in-the-Loop 검수 상태
export type FieldApproval = 'pending' | 'approved' | 'rejected'

export interface FieldEdit {
	editedValue: string
	editedAt: number
}

export interface AuditEntry {
	at: number
	action: 'edit' | 'approve' | 'reject' | 'reset'
	fieldName: string
	from?: string
	to?: string
}

interface OcrStore {
	hoveredBlockId: number | null
	clickedBlockId: number | null
	clickedPdfBlockId: number | null
	blocks: Block[]
	fieldHighlight: FieldHighlight | null
	roiMode: boolean
	rois: Roi[]
	hoveredRoiId: string | null
	setHoveredBlockId: (blockId: number | null) => void
	setClickedBlockId: (blockId: number | null) => void
	setClickedPdfBlockId: (blockId: number | null) => void
	setBlocks: (blocks: Block[]) => void
	setFieldHighlight: (h: FieldHighlight | null) => void
	setRoiMode: (on: boolean) => void
	addRoi: (bbox: [number, number, number, number]) => string  // returns id
	removeRoi: (id: string) => void
	renameRoi: (id: string, name: string) => void
	updateRoi: (id: string, patch: Partial<Roi>) => void
	clearRois: () => void
	setHoveredRoiId: (id: string | null) => void
	// HITL
	fieldEdits: Record<string, FieldEdit>
	fieldApprovals: Record<string, FieldApproval>
	auditLog: AuditEntry[]
	editField: (fieldName: string, newValue: string, originalValue: string) => void
	resetField: (fieldName: string) => void
	approveField: (fieldName: string) => void
	rejectField: (fieldName: string) => void
	approveAll: (fieldNames: string[]) => void
	resetHitl: () => void
}

export const useOcrStore = create<OcrStore>((set, get) => ({
	hoveredBlockId: null,
	clickedBlockId: null,
	clickedPdfBlockId: null,
	blocks: [],
	fieldHighlight: null,
	roiMode: false,
	rois: [],
	hoveredRoiId: null,
	setHoveredBlockId: blockId =>
		set({ hoveredBlockId: blockId, clickedBlockId: null, clickedPdfBlockId: null }),
	setClickedBlockId: blockId => set({ clickedBlockId: blockId, hoveredBlockId: blockId }),
	setClickedPdfBlockId: blockId => set({ clickedPdfBlockId: blockId, hoveredBlockId: blockId }),
	setBlocks: blocks => set({ blocks }),
	setFieldHighlight: h => set({ fieldHighlight: h }),
	setRoiMode: on => set({ roiMode: on }),
	addRoi: bbox => {
		const id = `roi-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
		const index = get().rois.length + 1
		const next: Roi = { id, name: `영역 ${index}`, bbox, status: 'idle' }
		set(s => ({ rois: [...s.rois, next] }))
		return id
	},
	removeRoi: id => set(s => ({ rois: s.rois.filter(r => r.id !== id) })),
	renameRoi: (id, name) =>
		set(s => ({ rois: s.rois.map(r => (r.id === id ? { ...r, name } : r)) })),
	updateRoi: (id, patch) =>
		set(s => ({ rois: s.rois.map(r => (r.id === id ? { ...r, ...patch } : r)) })),
	clearRois: () => set({ rois: [] }),
	setHoveredRoiId: id => set({ hoveredRoiId: id }),
	// HITL
	fieldEdits: {},
	fieldApprovals: {},
	auditLog: [],
	editField: (fieldName, newValue, originalValue) =>
		set(s => ({
			fieldEdits: { ...s.fieldEdits, [fieldName]: { editedValue: newValue, editedAt: Date.now() } },
			auditLog: [
				...s.auditLog,
				{ at: Date.now(), action: 'edit', fieldName, from: originalValue, to: newValue },
			],
		})),
	resetField: fieldName =>
		set(s => {
			const { [fieldName]: _omit, ...rest } = s.fieldEdits
			return {
				fieldEdits: rest,
				auditLog: [
					...s.auditLog,
					{ at: Date.now(), action: 'reset', fieldName },
				],
			}
		}),
	approveField: fieldName =>
		set(s => ({
			fieldApprovals: { ...s.fieldApprovals, [fieldName]: 'approved' },
			auditLog: [...s.auditLog, { at: Date.now(), action: 'approve', fieldName }],
		})),
	rejectField: fieldName =>
		set(s => ({
			fieldApprovals: { ...s.fieldApprovals, [fieldName]: 'rejected' },
			auditLog: [...s.auditLog, { at: Date.now(), action: 'reject', fieldName }],
		})),
	approveAll: fieldNames =>
		set(s => {
			const next = { ...s.fieldApprovals }
			const newLog: AuditEntry[] = []
			fieldNames.forEach(n => {
				if (next[n] !== 'approved') {
					next[n] = 'approved'
					newLog.push({ at: Date.now(), action: 'approve', fieldName: n })
				}
			})
			return { fieldApprovals: next, auditLog: [...s.auditLog, ...newLog] }
		}),
	resetHitl: () => set({ fieldEdits: {}, fieldApprovals: {}, auditLog: [] }),
}))

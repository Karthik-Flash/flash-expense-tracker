// Insights (5F): Export, Profile, and for the admin People who use Flash. Every figure and
// every file comes from the server (D-088, D-146); this screen only lays it out.

import { useState } from 'react'

import { useSnapshot } from '../data/store.ts'
import { fileName, MIME, PRESETS, rangeOf, type Preset } from '../exportRange.ts'
import { today } from '../lib/dates.ts'
import { isNativeApp, shareFile } from '../native/sms.ts'
import { useApp, useNav } from '../state.tsx'
import { Button, Header, Icon, Loaded, RowButton, Section } from '../ui.tsx'
import type { SheetName } from '../view.ts'
import { InvestmentsSetting } from './Account.tsx'

export function Insights() {
  const [load, retry] = useSnapshot()
  const { open } = useNav()
  const { signOut } = useApp()
  const go = (sheet: SheetName) => () => open({ sheet })
  return (
    <>
      <Header title="Insights" />
      <Loaded load={load} retry={retry}>
        {(s) => {
          const names = s.profile?.names ?? []
          const admin = s.account?.role === 'admin' ? s.admin : undefined
          const active = admin?.invites.filter((i) => !i.used_utc && !i.revoked_utc && (!i.expires_utc || Date.parse(i.expires_utc) > Date.now())).length ?? 0
          return (
            <>
              <ExportSection />
              <Section title="Profile">
                <Link onClick={go('profile')} title="Your name as banks show it" detail={names.length ? names.join(', ') : 'Not set: "Is this you?" needs it'} />
                <Link onClick={go('sms')} title="Bank SMS" detail={isNativeApp() ? 'This phone: status, Sync now' : 'Your phones; SMS are read by the Android app'} />
                <div>
                  <InvestmentsSetting server={s.profile?.settings} />
                </div>
                <Link onClick={go('privacy')} title="What Flash stores" detail="Only your banks' SMS, never shared" />
                <Link onClick={go('speed')} title="Speed and sync" detail="Launch times, changes waiting to sync" />
                <Link onClick={go('delete')} title="Delete my account" detail="Everything of yours, for good" />
                <Link onClick={signOut} title="Sign out" detail={s.account?.email ?? ''} />
              </Section>
              {admin && (
                <Section title="Admin">
                  <Link
                    onClick={go('members')}
                    title="People who use Flash"
                    detail={`${admin.members.length} ${admin.members.length === 1 ? 'person' : 'people'} · ${active} ${active === 1 ? 'invite' : 'invites'} open`}
                  />
                </Section>
              )}
            </>
          )
        }}
      </Loaded>
    </>
  )
}

/** Export (5F, D-146): CSV or Excel of a range, built by the server. On the web a download,
 *  in the Android app the share sheet. */
function ExportSection() {
  const { api } = useApp()
  const [preset, setPreset] = useState<Preset>('month')
  const [custom, setCustom] = useState<[string, string]>([today().slice(0, 8) + '01', today()])
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [start, end] = rangeOf(preset, custom)
  const save = async (format: 'csv' | 'xlsx') => {
    setBusy(true)
    setStatus('')
    try {
      const blob = await api.exportFile(start, end, format)
      const name = fileName(start, end, format)
      if (isNativeApp()) {
        const base64 = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '')
          reader.onerror = () => reject(new Error('Could not read the file.'))
          reader.readAsDataURL(blob)
        })
        await shareFile(name, MIME[format], base64)
      } else {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = name
        a.click()
        setTimeout(() => URL.revokeObjectURL(url), 10_000)
      }
      setStatus(`Saved ${name}`)
    } catch (e) {
      setStatus(e instanceof Error ? `Could not export: ${e.message}` : 'Could not export. Try again.')
    } finally {
      setBusy(false)
    }
  }
  const field = 'min-h-11 min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 text-sm text-ink'
  return (
    <Section title="Export">
      <div className="space-y-3 px-4 py-3 text-sm">
        <label className="block text-xs text-muted">
          Period
          <select className={`${field} mt-1 w-full`} value={preset} onChange={(e) => setPreset(e.target.value as Preset)}>
            {PRESETS.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
          </select>
        </label>
        {preset === 'custom' && (
          <div className="flex flex-wrap gap-2">
            <label className="flex min-w-36 flex-1 flex-col text-xs text-muted">
              From
              <input type="date" className={field} value={custom[0]} max={today()} onChange={(e) => setCustom([e.target.value, custom[1]])} />
            </label>
            <label className="flex min-w-36 flex-1 flex-col text-xs text-muted">
              To
              <input type="date" className={field} value={custom[1]} max={today()} onChange={(e) => setCustom([custom[0], e.target.value])} />
            </label>
          </div>
        )}
        <p className="text-xs text-muted">{start} to {end}, IST. No SMS text, only what the app shows.</p>
        <div className="flex flex-wrap gap-2">
          <Button kind="primary" disabled={busy || !start || !end} onClick={() => void save('xlsx')}>Excel</Button>
          <Button disabled={busy || !start || !end} onClick={() => void save('csv')}>CSV</Button>
        </div>
        {status && <p className="text-xs text-muted" role="status">{status}</p>}
      </div>
    </Section>
  )
}

function Link({ onClick, title, detail }: { onClick: () => void; title: string; detail: string }) {
  return (
    <RowButton onClick={onClick}>
      <span className="min-w-[min(6rem,35vw)] flex-1">
        <span className="block">{title}</span>
        {detail && <span className="block truncate text-xs text-muted">{detail}</span>}
      </span>
      <Icon name="chevron-right" className="text-muted" />
    </RowButton>
  )
}

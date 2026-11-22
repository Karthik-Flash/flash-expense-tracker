// Insights (5F): Profile, and for the admin People who use Flash. Every figure comes from the
// server (D-088); this screen only lays it out.

import { useSnapshot } from '../data/store.ts'
import { isNativeApp } from '../native/sms.ts'
import { useApp, useNav } from '../state.tsx'
import { Header, Icon, Loaded, RowButton, Section } from '../ui.tsx'
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

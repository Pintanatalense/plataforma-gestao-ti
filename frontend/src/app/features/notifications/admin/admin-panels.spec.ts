import { TestBed } from '@angular/core/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { of, throwError } from 'rxjs';
import {
  ChannelHealth,
  DeliveryItem,
  HealthResponse,
  NotificationsAdminService,
  RuleItem
} from '../../../core/services/notifications-admin.service';
import { CHANNEL_NAMES, ChannelsComponent, channelState } from './channels.component';
import { DeliveriesComponent } from './deliveries.component';
import { RulesComponent, apiErrorMessage, parseList } from './rules.component';

function delivery(id: string, status: string, extra: Partial<DeliveryItem> = {}): DeliveryItem {
  return {
    id, event_id: 'e', event_type: 'ticket.created', channel: 'email', status, priority: 'normal',
    recipient_email: `${id}@x.y`, address: 'a', title: 't', attempts: 1, max_attempts: 5, last_error: null,
    next_attempt_at: '2026-10-17T12:00:00Z', created_at: '2026-10-17T12:00:00Z', sent_at: null,
    provider_status: null, provider_status_at: null, origin: 'rule', ...extra
  };
}

/** `settled=false` para componentes com polling (setInterval): `whenStable` nunca resolveria. */
async function mount<T>(component: new () => T, api: object, settled = true) {
  await TestBed.configureTestingModule({
    imports: [component as never],
    providers: [provideAnimationsAsync(), { provide: NotificationsAdminService, useValue: api }]
  }).compileComponents();
  const fixture = TestBed.createComponent(component);
  fixture.detectChanges();
  if (settled) await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('DeliveriesComponent', () => {
  it('offers resend only for DEAD and cancel only for PENDING', async () => {
    const api = {
      listDeliveries: vi.fn().mockReturnValue(
        of({ total: 3, items: [delivery('a', 'DEAD'), delivery('b', 'PENDING'), delivery('c', 'SENT')] })
      ),
      resend: vi.fn().mockReturnValue(of({ id: 'n', status: 'PENDING' })),
      cancel: vi.fn().mockReturnValue(of({ id: 'b', status: 'CANCELLED' })),
      getDelivery: vi.fn()
    };
    const fixture = await mount(DeliveriesComponent, api);
    const rows: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[data-testid="delivery-row"]'));

    expect(rows).toHaveLength(3);
    expect(rows[0].querySelector('[data-testid="resend"]')).toBeTruthy();
    expect(rows[0].querySelector('[data-testid="cancel"]')).toBeNull();
    expect(rows[1].querySelector('[data-testid="cancel"]')).toBeTruthy();
    expect(rows[2].querySelector('button')).toBeNull();

    (rows[0].querySelector('[data-testid="resend"]') as HTMLElement).click();
    expect(api.resend).toHaveBeenCalledWith('a');
    (rows[1].querySelector('[data-testid="cancel"]') as HTMLElement).click();
    expect(api.cancel).toHaveBeenCalledWith('b');
  });

  it('passes filters and pagination to the API', async () => {
    const api = { listDeliveries: vi.fn().mockReturnValue(of({ total: 60, items: [delivery('a', 'SENT')] })) };
    const fixture = await mount(DeliveriesComponent, api);
    const component = fixture.componentInstance;

    component.filters.status = 'DEAD';
    component.filters.recipient = 'ana';
    component.search();
    expect(api.listDeliveries).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'DEAD', recipient: 'ana', offset: 0 }));
    component.page(1);
    expect(api.listDeliveries).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 25 }));
    component.page(-1);
    component.page(-1);
    expect(api.listDeliveries).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }));
  });

  it('shows the attempt log of the selected delivery', async () => {
    const api = {
      listDeliveries: vi.fn().mockReturnValue(of({ total: 1, items: [delivery('a', 'DEAD')] })),
      getDelivery: vi.fn().mockReturnValue(
        of({
          ...delivery('a', 'DEAD'), last_error: '550 sem caixa',
          attempt_log: [{ attempt_no: 1, started_at: '2026-10-17T12:00:00Z', finished_at: null, outcome: 'permanent', error: '550 sem caixa' }],
          event_payload: { ticket_id: 'T' }
        })
      )
    };
    const fixture = await mount(DeliveriesComponent, api);
    (fixture.nativeElement.querySelector('[data-testid="delivery-row"]') as HTMLElement).click();
    fixture.detectChanges();
    const detail = fixture.nativeElement.querySelector('[data-testid="delivery-detail"]');
    expect(detail.textContent).toContain('550 sem caixa');
    expect(detail.textContent).toContain('permanent');
  });

  it('tells "accepted by the gateway" apart from what the provider confirmed', async () => {
    const api = {
      listDeliveries: vi.fn().mockReturnValue(of({ total: 2, items: [
        delivery('a', 'SENT', { channel: 'whatsapp', provider_status: 'read', provider_status_at: '2026-10-17T12:05:00Z' }),
        delivery('b', 'SENT')
      ] })),
      getDelivery: vi.fn().mockReturnValue(of({ ...delivery('b', 'SENT', { origin: 'direct' }), attempt_log: [], event_payload: {} }))
    };
    const fixture = await mount(DeliveriesComponent, api);
    const rows: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[data-testid="delivery-row"]'));
    expect(rows[0].textContent).toContain('Aceita pelo gateway');
    expect(rows[0].querySelector('[data-testid="provider-status"]')?.textContent).toContain('Lida');
    expect(rows[0].textContent).toContain('WhatsApp');
    expect(rows[1].querySelector('[data-testid="provider-status"]')?.textContent).toContain('—');

    rows[1].click();
    fixture.detectChanges();
    const detail = fixture.nativeElement.querySelector('[data-testid="delivery-detail"]');
    expect(detail.textContent).toContain('Mensagem direta');
    expect(detail.querySelector('[data-testid="detail-confirmation"]').textContent).toContain('aceita pelo gateway');
  });

  it('sends the new filters (origin, confirmation, address, text) to the API', async () => {
    const api = { listDeliveries: vi.fn().mockReturnValue(of({ total: 0, items: [] })) };
    const fixture = await mount(DeliveriesComponent, api);
    const c = fixture.componentInstance;
    Object.assign(c.filters, { origin: 'direct', provider_status: 'none', address: '8590', q: 'AnyDesk' });
    c.search();
    expect(api.listDeliveries).toHaveBeenLastCalledWith(
      expect.objectContaining({ origin: 'direct', provider_status: 'none', address: '8590', q: 'AnyDesk', offset: 0 })
    );
  });

  it('shows an error when listing fails', async () => {
    const api = { listDeliveries: vi.fn().mockReturnValue(throwError(() => new Error('x'))) };
    const fixture = await mount(DeliveriesComponent, api);
    expect(fixture.nativeElement.querySelector('[role="alert"]')?.textContent).toContain('Não foi possível');
  });
});

describe('RulesComponent', () => {
  const RULE: RuleItem = {
    id: 'r1', code: 'ticket.created.staff', is_system: true, name: 'Novo chamado', enabled: true,
    event_type: 'ticket.created', condition: { exclude_actor: false, payload_equals: { x: 1 } },
    audience: ['sector_attendants'], channels: ['in_app'], template_code: 'ticket.created.staff',
    escalation: { after_minutes: 30, until: 'first_response', audience: ['admins'] }, fallback_channel: 'email', in_catalog: true
  };
  const OPTIONS = {
    channels: ['email', 'in_app', 'preferred'], templates: ['generic'], selectors: ['admins'],
    events: [
      { code: 'ticket.created', label: 'Chamado aberto', area: 'Chamados', payload_keys: [], escalation: true },
      { code: 'stock.below_minimum', label: 'Estoque abaixo do mínimo', area: 'Estoque', payload_keys: [], escalation: false }
    ],
    audiences: { admins: 'Administradores' },
    escalation_until: { first_response: 'enquanto ninguém responder', resolved: 'enquanto não resolver' }
  };

  function api(over: object = {}) {
    return {
      listRules: vi.fn().mockReturnValue(of({ items: [RULE], options: OPTIONS })),
      createRule: vi.fn().mockReturnValue(of(RULE)),
      updateRule: vi.fn().mockReturnValue(of(RULE)),
      deleteRule: vi.fn().mockReturnValue(of(undefined)),
      simulate: vi.fn().mockReturnValue(of({ deliveries: [] })),
      ...over
    };
  }

  it('lists rules and hides delete for system rules', async () => {
    const fixture = await mount(RulesComponent, api());
    const row = fixture.nativeElement.querySelector('[data-testid="rule-row"]') as HTMLElement;
    expect(row.textContent).toContain('Novo chamado');
    expect(row.textContent).toContain('padrão');
    expect(row.querySelector('[aria-label="Excluir"]')).toBeNull();
  });

  it('creates a rule with parsed audience and keeps unknown condition keys when editing', async () => {
    const a = api();
    const fixture = await mount(RulesComponent, a);
    const c = fixture.componentInstance;

    c.startNew();
    const f = c.form()!;
    Object.assign(f, { name: ' Estoque ', event_type: 'stock.below_minimum', audienceText: 'admins, role:Gestão,, admins', template_code: 'generic', min_priority: 'high' });
    f.channels = ['in_app', 'email'];
    c.save();
    expect(a.createRule).toHaveBeenCalledWith({
      name: 'Estoque', enabled: true, event_type: 'stock.below_minimum', condition: { min_priority: 'high' },
      audience: ['admins', 'role:Gestão'], channels: ['in_app', 'email'], template_code: 'generic',
      escalation: {}, fallback_channel: null
    });

    c.edit(RULE);
    c.save();
    const sent = a.updateRule.mock.calls[0][1];
    expect(a.updateRule.mock.calls[0][0]).toBe('r1');
    expect(sent.condition).toEqual({ payload_equals: { x: 1 }, exclude_actor: false });
    expect([sent.escalation, sent.fallback_channel]).toEqual([{ after_minutes: 30, until: 'first_response', audience: ['admins'] }, 'email']);
  });

  it('offers escalation only for ticket events and never sends it for others', async () => {
    const a = api();
    const fixture = await mount(RulesComponent, a);
    const c = fixture.componentInstance;
    c.startNew();
    const f = c.form()!;
    Object.assign(f, { name: 'x', event_type: 'ticket.created', audienceText: 'requester', escalate: true, escalation_minutes: '45', escalation_audienceText: 'admins, role:Gestão' });
    c.setEscalationChannel(f, 'email', true);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-testid="rule-escalation-form"]')).toBeTruthy();
    expect(c.fallbackChannels()).toEqual(['email', 'in_app']);
    c.save();
    expect(a.createRule.mock.calls[0][0].escalation).toEqual({ after_minutes: 45, until: 'first_response', audience: ['admins', 'role:Gestão'], channels: ['email'] });

    c.startNew();
    Object.assign(c.form()!, { name: 'y', event_type: 'stock.below_minimum', audienceText: 'admins', escalate: true });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[data-testid="rule-escalate"]')).toBeNull();
    c.save();
    expect(a.createRule.mock.calls[1][0].escalation).toEqual({});
  });

  it('shows the event label and flags rules outside the catalog', async () => {
    const custom = { ...RULE, id: 'r2', is_system: false, event_type: 'x.y', in_catalog: false, escalation: {}, fallback_channel: null };
    const fixture = await mount(RulesComponent, api({ listRules: vi.fn().mockReturnValue(of({ items: [RULE, custom], options: OPTIONS })) }));
    const rows: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[data-testid="rule-row"]'));
    expect(rows[0].textContent).toContain('Chamado aberto');
    expect(rows[0].querySelector('[data-testid="rule-escalation"]')?.textContent).toContain('30 min');
    expect(rows[0].textContent).toContain('se falhar: email');
    expect(rows[1].textContent).toContain('fora do catálogo');
  });

  it('shows the server validation message and keeps the form open', async () => {
    const err = { error: { error: { code: 'VALIDATION_ERROR', details: [{ msg: 'Value error, Canais desconhecidos: [pombo]' }] } } };
    const fixture = await mount(RulesComponent, api({ createRule: vi.fn().mockReturnValue(throwError(() => err)) }));
    const c = fixture.componentInstance;
    c.startNew();
    c.save();
    expect(c.error()).toBe('Canais desconhecidos: [pombo]');
    expect(c.form()).not.toBeNull();
  });

  it('toggles a rule through the API with its full definition', async () => {
    const a = api();
    const fixture = await mount(RulesComponent, a);
    fixture.componentInstance.toggle(RULE, false);
    expect(a.updateRule).toHaveBeenCalledWith('r1', expect.objectContaining({
      enabled: false, audience: ['sector_attendants'], fallback_channel: 'email',
      escalation: { after_minutes: 30, until: 'first_response', audience: ['admins'] }  // ligar/desligar não apaga o escalonamento
    }));
  });

  it('refuses a simulation with invalid JSON without calling the API', async () => {
    const a = api();
    const fixture = await mount(RulesComponent, a);
    const c = fixture.componentInstance;
    c.simPayload = '{quebrado';
    c.simulate();
    expect(a.simulate).not.toHaveBeenCalled();
    expect(c.simError()).toContain('JSON');

    c.simPayload = '{"a": 1}';
    c.simulate();
    expect(a.simulate).toHaveBeenCalledWith({ event_type: 'ticket.created', priority: 'normal', payload: { a: 1 } });
    expect(c.simulated()).toEqual([]);
  });
});

describe('helpers', () => {
  it('parseList trims, drops empties and duplicates', () => {
    expect(parseList(' a, b\n,,a ,c')).toEqual(['a', 'b', 'c']);
    expect(parseList('')).toEqual([]);
  });

  it('apiErrorMessage prefers validation details, then message, then the fallback', () => {
    expect(apiErrorMessage({ error: { error: { details: [{ msg: 'Value error, X' }, { msg: 'Y' }] } } }, 'f')).toBe('X Y');
    expect(apiErrorMessage({ error: { error: { message: 'Regra' } } }, 'f')).toBe('Regra');
    expect(apiErrorMessage({}, 'f')).toBe('f');
  });
});

describe('ChannelsComponent', () => {
  const base = { sent: 0, last_sent_at: null, oldest_pending_at: null, failures_last_hour: 0, attempts_last_hour: 0, last_error: null, last_error_at: null };
  function health(over: Partial<HealthResponse['worker']> = {}, channels: ChannelHealth[] = []): HealthResponse {
    return {
      worker: { status: 'healthy', beat_at: '2026-10-17T12:00:00Z', totals: {}, ...over },
      events_waiting: { count: 0, oldest_at: null },
      channels
    };
  }

  it('channelState picks the worst signal', () => {
    expect(channelState({ enabled: false, circuit_open: true, dead: 3 })).toBe('off');
    expect(channelState({ enabled: true, circuit_open: true, dead: 3 })).toBe('degraded');
    expect(channelState({ enabled: true, circuit_open: false, dead: 3 })).toBe('attention');
    expect(channelState({ enabled: true, circuit_open: false, dead: 0 })).toBe('ok');
    expect(CHANNEL_NAMES['in_app']).toBe('Caixa de entrada');
  });

  it('flags a stopped worker and a degraded channel', async () => {
    const api = {
      health: vi.fn().mockReturnValue(
        of(health({ status: 'stale' }, [{ ...base, channel: 'email', enabled: true, circuit_open: true, pending: 4, dead: 1, last_error: 'smtp caiu', last_error_at: '2026-10-17T11:00:00Z' }]))
      ),
      listJobs: vi.fn().mockReturnValue(of({ items: [] })),
      testChannel: vi.fn().mockReturnValue(of({ channel: 'email', ok: false, detail: 'Desabilitado.' }))
    };
    const fixture = await mount(ChannelsComponent, api, false);
    const text = fixture.nativeElement.textContent;
    expect(fixture.nativeElement.querySelector('[data-testid="worker-status"]').classList.contains('w-stale')).toBe(true);
    expect(text).toContain('Degradado');
    expect(text).toContain('smtp caiu');

    (fixture.nativeElement.querySelector('[data-testid="test-email"]') as HTMLElement).click();
    fixture.detectChanges();
    expect(api.testChannel).toHaveBeenCalledWith('email');
    expect(fixture.nativeElement.textContent).toContain('Desabilitado.');
  });

  it('reports a failed schedule load instead of an empty table', async () => {
    const api = {
      health: vi.fn().mockReturnValue(of(health({ status: 'healthy' }, []))),
      listJobs: vi.fn().mockReturnValue(throwError(() => new Error('x'))),
      testChannel: vi.fn()
    };
    const fixture = await mount(ChannelsComponent, api, false);
    expect(fixture.nativeElement.querySelector('[data-testid="jobs-error"]')).toBeTruthy();
  });

  it('with `only` it shows just that channel and hides the worker schedule', async () => {
    const api = {
      health: vi.fn().mockReturnValue(
        of(health({}, [
          { ...base, channel: 'email', enabled: true, circuit_open: false, pending: 0, dead: 0 },
          { ...base, channel: 'whatsapp', enabled: false, circuit_open: false, pending: 0, dead: 0 }
        ]))
      ),
      listJobs: vi.fn().mockReturnValue(of({ items: [] })),
      testChannel: vi.fn()
    };
    const fixture = await mount(ChannelsComponent, api, false);
    expect(fixture.nativeElement.querySelectorAll('[data-testid="channel-card"]').length).toBe(2);

    fixture.componentRef.setInput('only', 'whatsapp');
    fixture.detectChanges();
    const cards = fixture.nativeElement.querySelectorAll('[data-testid="channel-card"]');
    expect(cards.length).toBe(1);
    expect(cards[0].textContent).toContain('WhatsApp');
    expect(fixture.nativeElement.querySelector('[data-testid="jobs-table"]')).toBeNull();
  });

  it('runs a job on demand and only when it is enabled', async () => {
    const jobs = [
      { name: 'backup.daily', schedule: 'daily:02:00', enabled: true, next_run_at: '2026-10-18T05:00:00Z', last_run_at: '2026-10-17T05:00:00Z', last_status: 'error', last_error: 'disco cheio' },
      { name: 'retention.cleanup', schedule: 'daily:03:30', enabled: false, next_run_at: '2026-10-18T06:30:00Z', last_run_at: null, last_status: null, last_error: null }
    ];
    const api = {
      health: vi.fn().mockReturnValue(of(health())),
      listJobs: vi.fn().mockReturnValue(of({ items: jobs })),
      runJob: vi.fn().mockReturnValue(of({})),
      setJobEnabled: vi.fn().mockReturnValue(of({}))
    };
    const fixture = await mount(ChannelsComponent, api, false);
    const buttons: HTMLButtonElement[] = Array.from(fixture.nativeElement.querySelectorAll('[data-testid="run-job"]'));
    expect(buttons.map((b) => b.disabled)).toEqual([false, true]);
    expect(fixture.nativeElement.textContent).toContain('disco cheio');

    buttons[0].click();
    expect(api.runJob).toHaveBeenCalledWith('backup.daily');
    fixture.componentInstance.setEnabled(jobs[1], true);
    expect(api.setJobEnabled).toHaveBeenCalledWith('retention.cleanup', true);
  });
});

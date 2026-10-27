import { TestBed } from '@angular/core/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { HttpErrorResponse } from '@angular/common/http';
import { of, throwError } from 'rxjs';
import { AuthService } from '../../../core/auth/auth.service';
import { MessagesService, OutboundMessage, PreviewResponse } from '../../../core/services/messages.service';
import { MessageComposeComponent, customVariables } from './compose.component';
import { MessageHistoryComponent, deliverySummary } from './history.component';
import { MessagesPageComponent } from './messages-page.component';
import { MessageTemplatesComponent } from './templates.component';

const CAPS = {
  rich_text: false, inbound: false, max_len: null, rate_per_second: null, formatting: 'plain' as const,
  attachments: false, typing: false, delivery_receipts: false, read_receipts: false
};

function preview(queued: number): PreviewResponse {
  return {
    channel: 'in_app', capabilities: CAPS, queued, skipped: 1,
    recipients: [
      { user_id: 'u1', email: 'ana@x', name: 'Ana', outcome: 'queued', rendered: { title: 'Aviso', text: 'Olá Ana' } },
      { user_id: 'u2', email: 'bia@x', name: 'Bia', outcome: 'no_address' }
    ]
  };
}

function outbound(extra: Partial<OutboundMessage> = {}): OutboundMessage {
  return {
    id: 'm1', kind: 'manual', channel: 'in_app', subject: 'Aviso', priority: 'normal', status: 'QUEUED',
    queued_count: 1, skipped_count: 0, created_at: '2026-10-27T12:00:00Z', created_by: 'u0', cancelled_at: null,
    deliveries: { PENDING: 1 }, ...extra
  };
}

function api(overrides: object = {}) {
  return {
    listTemplates: vi.fn().mockReturnValue(of({ items: [], builtin_variables: ['nome', 'email', 'empresa', 'data', 'hora'] })),
    searchRecipients: vi.fn().mockReturnValue(of({
      items: [{ user_id: 'u1', name: 'Ana', email: 'ana@x', channels: ['email', 'in_app'] }], reaches_everyone: false
    })),
    preview: vi.fn().mockReturnValue(of(preview(1))),
    send: vi.fn().mockReturnValue(of(outbound())),
    sendTest: vi.fn().mockReturnValue(of(outbound({ kind: 'test' }))),
    list: vi.fn().mockReturnValue(of({ total: 0, items: [] })),
    get: vi.fn(),
    cancel: vi.fn(),
    ...overrides
  };
}

async function mount<T>(component: new () => T, service: object, auth?: object) {
  await TestBed.configureTestingModule({
    imports: [component as never],
    providers: [
      provideAnimationsAsync(),
      { provide: MessagesService, useValue: service },
      ...(auth ? [{ provide: AuthService, useValue: auth }] : [])
    ]
  }).compileComponents();
  const fixture = TestBed.createComponent(component);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('helpers', () => {
  it('customVariables lists only the ones the sender must fill', () => {
    expect(customVariables(['Oi {{ Nome }}', '{{setor}} em {{data}} {{setor}}'], ['nome', 'data'])).toEqual(['setor']);
  });

  it('deliverySummary reads in the useful order', () => {
    expect(deliverySummary({ SENT: 2, PENDING: 1 })).toBe('1 pendente · 2 aceita pelo gateway');
    expect(deliverySummary({})).toBe('—');
  });
});

describe('MessageComposeComponent', () => {
  it('only sends what was previewed, and a change invalidates the preview', async () => {
    const service = api();
    const fixture = await mount(MessageComposeComponent, service);
    const c = fixture.componentInstance;
    c.add(c.results()[0]);
    c.draft.body = 'Olá {{nome}}, setor {{setor}}';
    c.draft.variables = { setor: 'TI', velha: 'x' };
    fixture.detectChanges();
    const sendButton = () => fixture.nativeElement.querySelector('[data-testid="m-send"]') as HTMLButtonElement;
    expect(sendButton().disabled).toBe(true);

    c.runPreview();
    fixture.detectChanges();
    expect(service.preview).toHaveBeenCalledWith(expect.objectContaining({ recipient_ids: ['u1'], variables: { setor: 'TI' } }));
    expect(sendButton().disabled).toBe(false);
    expect(fixture.nativeElement.querySelector('[data-testid="m-preview-result"]').textContent).toContain('Não vinculou este canal');
    expect(fixture.nativeElement.querySelector('[data-testid="m-sample-text"]').textContent).toContain('Olá Ana');

    c.changed();
    fixture.detectChanges();
    expect(sendButton().disabled).toBe(true);
  });

  it('keeps the idempotency key on retry and renews it after a successful send', async () => {
    const failure = new HttpErrorResponse({ status: 0 });
    const service = api({
      send: vi.fn().mockReturnValueOnce(throwError(() => failure)).mockReturnValue(of(outbound()))
    });
    const fixture = await mount(MessageComposeComponent, service);
    const c = fixture.componentInstance;
    c.add(c.results()[0]);
    c.draft.body = 'Oi';
    c.runPreview();

    c.send();
    expect(c.error()).toContain('Sem conexão');
    c.send();
    const [firstKey, secondKey] = service.send.mock.calls.map((call: unknown[]) => call[1]);
    expect(secondKey).toBe(firstKey);
    expect(c.selected()).toEqual([]);  // formulário limpo depois do envio

    c.add({ user_id: 'u1', name: 'Ana', email: 'ana@x', channels: [] });
    c.draft.body = 'De novo';
    c.runPreview();
    c.send();
    expect(service.send.mock.calls[2][1]).not.toBe(firstKey);
  });

  it('asks for a recipient before the preview and fills the text from a template', async () => {
    const service = api({
      listTemplates: vi.fn().mockReturnValue(of({
        items: [{ id: 't1', code: 'x', name: 'Parada', channels: ['email'], subject: 'S', body: 'B', is_active: true, variables: [] }],
        builtin_variables: ['nome']
      }))
    });
    const fixture = await mount(MessageComposeComponent, service);
    const c = fixture.componentInstance;
    c.runPreview();
    expect(c.error()).toContain('destinatário');
    expect(service.preview).not.toHaveBeenCalled();

    expect(c.templatesFor()).toEqual([]);  // modelo só de e-mail não aparece no canal Caixa de entrada
    c.draft.channel = 'email';
    c.draft.template_id = 't1';
    c.applyTemplate();
    expect([c.draft.subject, c.draft.body]).toEqual(['S', 'B']);
  });
});

describe('MessageHistoryComponent', () => {
  it('offers cancel only while something is pending and shows each recipient outcome', async () => {
    const service = api({
      list: vi.fn().mockReturnValue(of({ total: 2, items: [outbound(), outbound({ id: 'm2', deliveries: { SENT: 1 } })] })),
      get: vi.fn().mockReturnValue(of({
        ...outbound(), body: 'Oi', variables: {}, template_id: null,
        recipients: [
          { user_id: 'u1', email: 'ana@x', name: 'Ana', outcome: 'queued',
            delivery: { delivery_id: 'd1', status: 'SENT', provider_status: 'read', attempts: 1, last_error: null } },
          { user_id: 'u2', email: 'bia@x', name: 'Bia', outcome: 'out_of_scope', delivery: null }
        ]
      })),
      cancel: vi.fn().mockReturnValue(of({ ...outbound({ status: 'CANCELLED' }), cancelled: 1 }))
    });
    const fixture = await mount(MessageHistoryComponent, service);
    const rows: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[data-testid="history-row"]'));
    expect(rows[0].querySelector('[data-testid="history-cancel"]')).toBeTruthy();
    expect(rows[1].querySelector('[data-testid="history-cancel"]')).toBeNull();

    rows[0].click();
    fixture.detectChanges();
    const detail = fixture.nativeElement.querySelector('[data-testid="history-detail"]').textContent;
    expect(detail).toContain('Aceita pelo gateway · Lida');
    expect(detail).toContain('Fora do seu setor');

    (rows[0].querySelector('[data-testid="history-cancel"]') as HTMLElement).click();
    expect(service.cancel).toHaveBeenCalledWith('m1');
  });
});

describe('MessageTemplatesComponent', () => {
  it('creates a template', async () => {
    const service = { ...api(), createTemplate: vi.fn().mockReturnValue(of({})), updateTemplate: vi.fn(), deleteTemplate: vi.fn() };
    const fixture = await mount(MessageTemplatesComponent, service);
    const c = fixture.componentInstance;
    c.startNew();
    Object.assign(c.form, { code: 'aviso', name: 'Aviso', body: 'Oi {{nome}}' });
    c.save('new');
    expect(service.createTemplate).toHaveBeenCalledWith(expect.objectContaining({ code: 'aviso', is_active: true }));
  });
});

describe('MessagesPageComponent', () => {
  it('shows compose only to senders and templates only to notification admins', async () => {
    const auth = { hasPermission: (p: string) => p === 'notifications.messages.read' };
    const fixture = await mount(MessagesPageComponent, api(), auth);
    const labels = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]')).map((t) => (t as HTMLElement).textContent?.trim());
    expect(labels).toEqual(['Histórico']);
  });
});

import { TestBed } from '@angular/core/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { of, throwError } from 'rxjs';
import { NotificationsAdminService, WhatsAppConfig } from '../../core/services/notifications-admin.service';
import { WhatsAppConfigComponent, safeQr } from './admin/whatsapp-config.component';

const QR = 'data:image/png;base64,QUJD';
const CONFIG: WhatsAppConfig = {
  enabled: false, provider: 'evolution', instance_name: 'gestao-ti', evolution_ready: true, send_interval_seconds: 4, max_per_hour: 10,
  access_token: '', app_secret: '', phone_number_id: '', graph_version: 'v21.0', template_name: '',
  template_language: 'pt_BR', app_base_url: '', display_phone: null, verified_name: null,
  verify_token: null, webhook_path: '/api/v1/integrations/whatsapp/webhook'
};
const STATUS = { provider: 'evolution', state: 'close', detail: '', display_phone: null } as const;

async function mount(api: object) {
  await TestBed.configureTestingModule({
    imports: [WhatsAppConfigComponent],
    providers: [provideAnimationsAsync(), { provide: NotificationsAdminService, useValue: api }]
  }).compileComponents();
  const fixture = TestBed.createComponent(WhatsAppConfigComponent);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}
const q = (f: { nativeElement: HTMLElement }, id: string) => f.nativeElement.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;

describe('safeQr', () => {
  it('accepts only embedded PNG/JPEG images', () => {
    expect(safeQr(QR)).toBe(QR);
    for (const bad of [null, undefined, '', 'https://x/y.png', 'javascript:alert(1)', 'data:text/html;base64,QUJD', 'data:image/svg+xml;base64,QUJD']) {
      expect(safeQr(bad as never)).toBeNull();
    }
  });
});

describe('WhatsAppConfigComponent com Evolution', () => {
  it('shows the Evolution form, the risk notice and no Meta webhook', async () => {
    const api = { getWhatsAppConfig: vi.fn().mockReturnValue(of(CONFIG)), whatsAppStatus: vi.fn().mockReturnValue(of(STATUS)) };
    const f = await mount(api);
    expect(q(f, 'wa-instance')).toBeTruthy();
    expect(q(f, 'wa-evolution-hint')?.textContent).toContain('não é oficial');
    expect(q(f, 'wa-webhook')).toBeNull();
    expect(q(f, 'wa-token')).toBeNull();
    expect(q(f, 'wa-state')?.textContent).toContain('Desconectado');
    expect(q(f, 'wa-not-ready')).toBeNull();
  });

  it('warns when the server has no Evolution key', async () => {
    const api = { getWhatsAppConfig: vi.fn().mockReturnValue(of({ ...CONFIG, evolution_ready: false })), whatsAppStatus: vi.fn().mockReturnValue(of(STATUS)) };
    const f = await mount(api);
    expect(q(f, 'wa-not-ready')?.textContent).toContain('EVOLUTION_API_KEY');
  });

  it('old servers without the provider field keep working as Meta', async () => {
    const { provider: _p, instance_name: _i, evolution_ready: _e, send_interval_seconds: _s, max_per_hour: _m, ...legacy } = CONFIG;
    const api = { getWhatsAppConfig: vi.fn().mockReturnValue(of(legacy)), whatsAppStatus: vi.fn() };
    const f = await mount(api);
    expect(f.componentInstance.config()!.provider).toBe('meta');
    expect(q(f, 'wa-token')).toBeTruthy();
    expect(api.whatsAppStatus).not.toHaveBeenCalled();
  });

  it('saves the provider and the trimmed instance name', async () => {
    const api = {
      getWhatsAppConfig: vi.fn().mockReturnValue(of(CONFIG)),
      whatsAppStatus: vi.fn().mockReturnValue(of(STATUS)),
      saveWhatsAppConfig: vi.fn().mockReturnValue(of({ ...CONFIG, enabled: true }))
    };
    const f = await mount(api);
    f.componentInstance.config.update((c) => ({ ...c!, enabled: true, instance_name: ' ti-matriz ' }));
    f.componentInstance.save();
    expect(api.saveWhatsAppConfig).toHaveBeenCalledWith(expect.objectContaining({ enabled: true, provider: 'evolution', instance_name: 'ti-matriz' }));
  });

  it('shows the QR code, keeps refreshing it and stops when the number connects', async () => {
    vi.useFakeTimers();
    try {
      const connecting = { ...STATUS, state: 'connecting', qr_base64: QR, pairing_code: null, count: 1 };
      const open = { ...STATUS, state: 'open', display_phone: '5585999990000', qr_base64: null, pairing_code: null, count: null };
      const connect = vi.fn().mockReturnValueOnce(of(connecting)).mockReturnValueOnce(of(connecting)).mockReturnValue(of(open));
      const api = { getWhatsAppConfig: vi.fn().mockReturnValue(of(CONFIG)), whatsAppStatus: vi.fn().mockReturnValue(of(STATUS)), whatsAppConnect: connect };
      const f = await mount(api);

      f.componentInstance.connect();
      f.detectChanges();
      expect((q(f, 'wa-qr') as HTMLImageElement).src).toBe(QR);

      await vi.advanceTimersByTimeAsync(5_000);
      expect(connect).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(5_000);
      f.detectChanges();
      expect(connect).toHaveBeenCalledTimes(3);
      expect(q(f, 'wa-qr')).toBeNull();
      expect(q(f, 'wa-state')?.textContent).toContain('Conectado');

      await vi.advanceTimersByTimeAsync(30_000);
      expect(connect).toHaveBeenCalledTimes(3); // parou de atualizar
    } finally {
      vi.useRealTimers();
    }
  });

  it('never renders a QR that is not an embedded image', async () => {
    const hostile = { ...STATUS, state: 'connecting', qr_base64: 'javascript:alert(1)', pairing_code: null, count: 1 };
    const api = { getWhatsAppConfig: vi.fn().mockReturnValue(of(CONFIG)), whatsAppStatus: vi.fn().mockReturnValue(of(STATUS)), whatsAppConnect: vi.fn().mockReturnValue(of(hostile)) };
    const f = await mount(api);
    f.componentInstance.connect();
    f.detectChanges();
    expect(q(f, 'wa-qr')).toBeNull();
    f.componentInstance['stopRefresh']();
  });

  it('reports a failed connection attempt and stops refreshing', async () => {
    const api = {
      getWhatsAppConfig: vi.fn().mockReturnValue(of(CONFIG)), whatsAppStatus: vi.fn().mockReturnValue(of(STATUS)),
      whatsAppConnect: vi.fn().mockReturnValue(throwError(() => ({ status: 400, error: { error: { message: 'Esta ação vale só para o provedor Evolution.' } } })))
    };
    const f = await mount(api);
    f.componentInstance.connect();
    expect(f.componentInstance.connecting()).toBe(false);
    expect(f.componentInstance['timer']).toBeNull();
  });

  it('disconnect is only offered while connected and clears the QR and the number', async () => {
    const api = {
      getWhatsAppConfig: vi.fn().mockReturnValue(of(CONFIG)),
      whatsAppStatus: vi.fn().mockReturnValue(of({ ...STATUS, state: 'open', display_phone: '5585999990000' })),
      whatsAppDisconnect: vi.fn().mockReturnValue(of({ ...STATUS }))
    };
    const f = await mount(api);
    expect((q(f, 'wa-disconnect') as HTMLButtonElement).disabled).toBe(false);
    (q(f, 'wa-disconnect') as HTMLButtonElement).click();
    f.detectChanges();
    expect(api.whatsAppDisconnect).toHaveBeenCalled();
    expect(f.componentInstance.status()!.display_phone).toBeNull();
    expect((q(f, 'wa-disconnect') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('WhatsAppConfigComponent: ritmo e teste', () => {
  it('saves the pacing next to the provider and shows the defaults for older servers', async () => {
    const { send_interval_seconds: _s, max_per_hour: _m, ...old } = CONFIG;
    const api = {
      getWhatsAppConfig: vi.fn().mockReturnValue(of(old)), whatsAppStatus: vi.fn().mockReturnValue(of(STATUS)),
      saveWhatsAppConfig: vi.fn().mockReturnValue(of(CONFIG))
    };
    const f = await mount(api);
    expect((q(f, 'wa-interval') as HTMLInputElement).value).toBe('4');
    expect((q(f, 'wa-per-hour') as HTMLInputElement).value).toBe('10');
    f.componentInstance.config.update((c) => ({ ...c!, send_interval_seconds: 8, max_per_hour: 5 }));
    f.componentInstance.save();
    expect(api.saveWhatsAppConfig).toHaveBeenCalledWith(expect.objectContaining({ send_interval_seconds: 8, max_per_hour: 5 }));
  });

  it('offers the test only for an enabled channel, sends digits only and shows the result', async () => {
    const api = {
      getWhatsAppConfig: vi.fn().mockReturnValue(of(CONFIG)), whatsAppStatus: vi.fn().mockReturnValue(of(STATUS)),
      whatsAppTest: vi.fn().mockReturnValue(of({ ok: true, detail: 'Mensagem enviada para o final 1234.' }))
    };
    const f = await mount(api);
    expect(q(f, 'wa-test')).toBeNull(); // canal desabilitado
    f.componentInstance.config.update((c) => ({ ...c!, enabled: true }));
    f.detectChanges();
    expect((q(f, 'wa-test-send') as HTMLButtonElement).disabled).toBe(true); // sem número
    f.componentInstance.testTo = '+55 (85) 99999-1234';
    f.componentInstance.sendTest();
    f.detectChanges();
    expect(api.whatsAppTest).toHaveBeenCalledWith('5585999991234');
    expect(q(f, 'wa-test-result')?.textContent).toContain('final 1234');
  });

  it('shows the server refusal of the test instead of failing silently', async () => {
    const err = { error: { error: { message: 'Limite de 5 testes por hora atingido. Tente mais tarde.' } } };
    const api = {
      getWhatsAppConfig: vi.fn().mockReturnValue(of({ ...CONFIG, enabled: true })), whatsAppStatus: vi.fn().mockReturnValue(of(STATUS)),
      whatsAppTest: vi.fn().mockReturnValue(throwError(() => err))
    };
    const f = await mount(api);
    f.componentInstance.testTo = '5585999991234';
    f.componentInstance.sendTest();
    f.detectChanges();
    expect(q(f, 'wa-test-result')?.textContent).toContain('Limite de 5 testes');
    expect(f.componentInstance.testing()).toBe(false);
  });
});

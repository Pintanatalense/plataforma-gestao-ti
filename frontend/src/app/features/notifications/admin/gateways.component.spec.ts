import { TestBed } from '@angular/core/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';
import { Gateway, NotificationsAdminService } from '../../../core/services/notifications-admin.service';
import { GatewaysComponent, featureList } from './gateways.component';

function gateway(channel: string, extra: Partial<Gateway> = {}): Gateway {
  return {
    channel, enabled: true, configured: true,
    capabilities: {
      rich_text: false, inbound: true, max_len: 4000, rate_per_second: 5, formatting: 'plain',
      attachments: false, typing: false, delivery_receipts: false, read_receipts: false
    },
    limits: { ceiling_rate_per_second: 5, rate_per_second: null, effective_rate_per_second: 5 },
    ...extra
  };
}

async function mount(api: object) {
  await TestBed.configureTestingModule({
    imports: [GatewaysComponent],
    providers: [provideAnimationsAsync(), provideRouter([]), { provide: NotificationsAdminService, useValue: api }]
  }).compileComponents();
  const fixture = TestBed.createComponent(GatewaysComponent);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('GatewaysComponent', () => {
  it('shows only what each channel really does and the WhatsApp anti-ban limits', async () => {
    const whatsapp = gateway('whatsapp', {
      provider: 'evolution',
      capabilities: { ...gateway('x').capabilities, formatting: 'whatsapp', delivery_receipts: true, read_receipts: true },
      limits: { ceiling_rate_per_second: 10, rate_per_second: null, effective_rate_per_second: 10, send_interval_seconds: 4, max_per_hour_per_person: 10 }
    });
    const inApp = gateway('in_app', { limits: { ceiling_rate_per_second: null, rate_per_second: null, effective_rate_per_second: null } });
    const slack = gateway('slack', { enabled: false, configured: false });
    const api = { listGateways: vi.fn().mockReturnValue(of({ items: [inApp, slack, whatsapp] })) };
    const fixture = await mount(api);
    const cards: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[data-testid="gateway-card"]'));

    expect(cards[0].textContent).toContain('Sem limite de envio');
    expect(cards[1].querySelector('[data-testid="gateway-state"]')?.textContent).toContain('Não configurado');
    expect(cards[1].querySelector('[data-testid="limit-input"]')).toBeNull();
    expect(cards[2].textContent).toContain('Evolution API');
    expect(cards[2].querySelector('[data-testid="wa-limits"]')?.textContent).toContain('10 mensagem(ns) por pessoa por hora');
    expect(featureList(whatsapp).filter((f) => f.on).map((f) => f.label)).toEqual(['Recebe mensagens', 'Confirma entrega', 'Confirma leitura']);
  });

  it('lowers and resets the limit through the API', async () => {
    const lowered = gateway('telegram', { limits: { ceiling_rate_per_second: 5, rate_per_second: 1, effective_rate_per_second: 1 } });
    const api = {
      listGateways: vi.fn().mockReturnValue(of({ items: [gateway('telegram')] })),
      updateGatewayLimit: vi.fn().mockReturnValueOnce(of(lowered)).mockReturnValueOnce(of(gateway('telegram')))
    };
    const fixture = await mount(api);
    const c = fixture.componentInstance;

    c.draft['telegram'] = 1;
    c.save(c.items()[0]);
    expect(api.updateGatewayLimit).toHaveBeenLastCalledWith('telegram', 1);
    expect(c.items()[0].limits.effective_rate_per_second).toBe(1);
    fixture.detectChanges();
    (fixture.nativeElement.querySelector('[data-testid="limit-reset"]') as HTMLElement).click();
    expect(api.updateGatewayLimit).toHaveBeenLastCalledWith('telegram', null);
  });

  it('refuses an empty limit locally and shows the server message', async () => {
    const api = {
      listGateways: vi.fn().mockReturnValue(of({ items: [gateway('telegram')] })),
      updateGatewayLimit: vi.fn().mockReturnValue(throwError(() => new HttpErrorResponse({
        status: 400,
        error: { error: { code: 'BUSINESS_RULE_VIOLATION', message: 'O limite só pode ser reduzido: o máximo deste canal é 5 envio(s) por segundo.' } }
      })))
    };
    const fixture = await mount(api);
    const c = fixture.componentInstance;

    c.draft['telegram'] = null;
    c.save(c.items()[0]);
    expect(api.updateGatewayLimit).not.toHaveBeenCalled();
    expect(c.error()).toContain('maior que zero');

    c.draft['telegram'] = 50;
    c.save(c.items()[0]);
    expect(c.error()).toContain('só pode ser reduzido');
  });
});

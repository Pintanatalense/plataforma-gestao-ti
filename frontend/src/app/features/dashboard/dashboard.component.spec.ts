import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { of, throwError } from 'rxjs';
import { AuthService } from '../../core/auth/auth.service';
import { AssetService } from '../../core/services/asset.service';
import { InventoryService } from '../../core/services/inventory.service';
import { StockService } from '../../core/services/stock.service';
import { TicketService } from '../service-desk/ticket.service';
import { Dashboard } from './dashboard.component';

const ticket = (status: string) => ({ id: status, title: 't', status, priority: 'LOW', created_at: '2026-01-01T00:00:00Z' });

describe('Dashboard', () => {
  let fixture: ComponentFixture<Dashboard>;
  let tickets: { listTickets: ReturnType<typeof vi.fn> };
  const text = (id: string) =>
    (fixture.nativeElement.querySelector(`[data-testid="${id}"]`) as HTMLElement | null)?.textContent?.trim() ?? null;

  async function mount(listTickets: ReturnType<typeof vi.fn>, stockResult = of([{ id: 's1', name: 'Cabo', quantity: 5, min_quantity: 1 }])) {
    tickets = { listTickets };
    await TestBed.configureTestingModule({
      imports: [Dashboard],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideAnimationsAsync(),
        { provide: AuthService, useValue: { hasPermission: () => true } },
        { provide: TicketService, useValue: tickets },
        { provide: AssetService, useValue: { getAssets: () => of([{ status: 'IN_USE' }, { status: 'IN_STOCK' }]) } },
        { provide: StockService, useValue: { getItems: () => stockResult } },
        { provide: InventoryService, useValue: { listAudits: () => of([{ status: 'OPENED' }]) } }
      ]
    }).compileComponents();
    fixture = TestBed.createComponent(Dashboard);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  it('shows the numbers and no warning when everything loads', async () => {
    await mount(vi.fn().mockReturnValue(of([ticket('OPENED'), ticket('IN_PROGRESS')])));
    expect(text('kpi-tickets')).toBe('2');
    expect(text('kpi-assets')).toBe('2');
    expect(text('kpi-stock')).toBe('1');
    expect(text('kpi-audits')).toBe('1');
    expect(text('dashboard-error')).toBeNull();
  });

  it('a failed source is shown as unavailable, never as zero, and the user is warned', async () => {
    await mount(vi.fn().mockReturnValue(throwError(() => ({ status: 500, error: {} }))));
    expect(text('kpi-tickets')).toBe('—'); // antes: "0 chamados"
    expect(text('kpi-assets')).toBe('2'); // as demais fontes seguem normais
    expect(text('dashboard-error')).toContain('chamados');
    expect(fixture.nativeElement.textContent).toContain('Dados indisponíveis');
  });

  it('does not claim stock is fine when the stock call failed', async () => {
    await mount(
      vi.fn().mockReturnValue(of([])),
      throwError(() => ({ status: 0 })) as never
    );
    const html = fixture.nativeElement.textContent as string;
    expect(text('kpi-stock')).toBe('—');
    expect(html).not.toContain('Estoque Regular'); // antes: falha mostrava "Estoque Regular"
    expect(html).not.toContain('acima da cota mínima');
    expect(text('dashboard-error')).toContain('estoque');
  });

  it('"Tentar novamente" reloads the data and clears the warning', async () => {
    const listTickets = vi
      .fn()
      .mockReturnValueOnce(throwError(() => ({ status: 500, error: {} })))
      .mockReturnValue(of([ticket('OPENED')]));
    await mount(listTickets);
    expect(text('kpi-tickets')).toBe('—');

    (fixture.nativeElement.querySelector('[data-testid="dashboard-retry"]') as HTMLButtonElement).click();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(listTickets).toHaveBeenCalledTimes(2);
    expect(text('kpi-tickets')).toBe('1');
    expect(text('dashboard-error')).toBeNull();
  });
});

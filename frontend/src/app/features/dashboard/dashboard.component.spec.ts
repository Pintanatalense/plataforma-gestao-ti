import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { Subject, of, throwError } from 'rxjs';
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

  /** Monta o painel com serviços falsos; só os métodos informados mudam (o resto responde com dados simples). */
  async function mountWith(overrides: { getItems?: ReturnType<typeof vi.fn>; listTickets?: ReturnType<typeof vi.fn> }) {
    await TestBed.configureTestingModule({
      imports: [Dashboard],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideAnimationsAsync(),
        { provide: AuthService, useValue: { hasPermission: () => true } },
        { provide: TicketService, useValue: { listTickets: overrides.listTickets ?? vi.fn().mockReturnValue(of([])) } },
        { provide: AssetService, useValue: { getAssets: () => of([]) } },
        { provide: StockService, useValue: { getItems: overrides.getItems ?? vi.fn().mockReturnValue(of([])) } },
        { provide: InventoryService, useValue: { listAudits: () => of([]) } }
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

  it('shows priority, status and weekday in Portuguese', async () => {
    const tickets = [
      { ...ticket('PENDING'), id: 'a', priority: 'MEDIUM' },
      { ...ticket('OPENED'), id: 'b', priority: 'CRITICAL' }
    ];
    await mount(vi.fn().mockReturnValue(of(tickets)));
    const html = fixture.nativeElement.textContent as string;
    expect(html).toContain('Média');
    expect(html).toContain('Crítica');
    expect(html).toContain('Pendente');
    expect(html).not.toMatch(/\bMEDIUM\b|\bCRITICAL\b|\bPENDING\b/);
    expect(html).toMatch(/(segunda|terça|quarta|quinta|sexta)-feira|sábado|domingo/);
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

  it('does not keep showing the previous stock list when a reload fails', async () => {
    const low = { id: 's1', name: 'Toner', quantity: 0, min_quantity: 5 };
    const getItems = vi
      .fn()
      .mockReturnValueOnce(of([low]))
      .mockReturnValue(throwError(() => ({ status: 500, error: {} })));
    TestBed.resetTestingModule();
    await mountWith({ getItems });
    expect(fixture.nativeElement.textContent).toContain('Toner');

    fixture.componentInstance.loadMetrics();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(text('kpi-stock')).toBe('—');
    expect(fixture.nativeElement.textContent).not.toContain('Toner');
  });

  it('ignores a slow answer from an earlier load that arrives after a newer one', async () => {
    const first = new Subject<unknown[]>();
    const listTickets = vi
      .fn()
      .mockReturnValueOnce(first) // carga 1: fica pendente
      .mockReturnValue(of([ticket('OPENED')])); // carga 2: responde na hora
    TestBed.resetTestingModule();
    await mountWith({ listTickets });

    fixture.componentInstance.loadMetrics(); // carga 2
    fixture.detectChanges();
    await fixture.whenStable();
    expect(text('kpi-tickets')).toBe('1');

    first.next([ticket('OPENED'), ticket('OPENED'), ticket('OPENED')]); // resposta atrasada da carga 1
    first.complete();
    fixture.detectChanges();
    expect(text('kpi-tickets')).toBe('1'); // não foi sobrescrito
  });
});

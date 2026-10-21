import { TestBed } from '@angular/core/testing';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { AssetService } from '../../../core/services/asset.service';
import { OrganizationService } from '../../../core/services/organization.service';
import { AssetGlpiImportComponent } from './asset-glpi-import.component';

function file(name: string): File {
  return new File(['<xml/>'], name, { type: 'text/xml' });
}

function fakeAssetService(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    getCategories: vi.fn().mockReturnValue(of([{ id: 'cat-1', name: 'Notebooks' }])),
    analyzeGlpiImport: vi.fn(),
    executeGlpiImport: vi.fn(),
    ...overrides
  };
}

function fakeOrgService() {
  return {
    getUnits: vi.fn().mockReturnValue(of([{ id: 'unit-1', name: 'Matriz', code: 'MTZ', is_active: true }]))
  };
}

async function mount(assetService: ReturnType<typeof fakeAssetService>, orgService = fakeOrgService()) {
  await TestBed.configureTestingModule({
    imports: [AssetGlpiImportComponent],
    providers: [
      provideAnimationsAsync(),
      provideRouter([]),
      { provide: AssetService, useValue: assetService },
      { provide: OrganizationService, useValue: orgService }
    ]
  }).compileComponents();
  const fixture = TestBed.createComponent(AssetGlpiImportComponent);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('AssetGlpiImportComponent', () => {
  it('loads categories and units on init', async () => {
    const assetService = fakeAssetService();
    const orgService = fakeOrgService();
    await mount(assetService, orgService);
    expect(assetService.getCategories).toHaveBeenCalled();
    expect(orgService.getUnits).toHaveBeenCalled();
  });

  it('analyzes files and classifies rows with the right default action, advancing to step 2', async () => {
    const assetService = fakeAssetService({
      analyzeGlpiImport: vi.fn().mockReturnValue(
        of({
          rows: [
            { filename: 'matched.xml', status: 'MATCHED', matched_asset_id: 'a-1', matched_asset_tag: 'PAT-1', parsed: { hostname: 'HOST-A' } },
            { filename: 'new.xml', status: 'NEW', serial_number: 'SN-2', suggested_name: 'HOST-B', parsed: { hostname: 'HOST-B' } },
            { filename: 'bad.xml', status: 'ERROR', error_message: 'XML malformado' }
          ]
        })
      )
    });
    const fixture = await mount(assetService);
    const component = fixture.componentInstance;

    component.selectedFiles = [file('matched.xml'), file('new.xml'), file('bad.xml')];
    component.analyzeFiles();

    expect(component.importStep).toBe(2);
    expect(component.rows).toHaveLength(3);
    expect(component.rows[0].action).toBe('update');
    expect(component.rows[1].action).toBe('create');
    expect(component.rows[2].action).toBe('skip');
  });

  it('requires tag/category/unit for new assets before confirming, and allows matched/skip rows through', async () => {
    const fixture = await mount(fakeAssetService());
    const component = fixture.componentInstance;

    component.rows = [
      {
        filename: 'new.xml',
        file: file('new.xml'),
        status: 'NEW',
        action: 'create',
        tag: '',
        name: 'HOST-B',
        categoryId: '',
        unitId: ''
      } as never
    ];

    expect(component.canConfirm).toBe(false);

    component.rows[0].tag = 'PAT-99';
    component.rows[0].categoryId = 'cat-1';
    component.rows[0].unitId = 'unit-1';
    expect(component.canConfirm).toBe(true);
  });

  it('executes the import with the decisions built from the rows and shows the result counts', async () => {
    const executeSpy = vi.fn().mockReturnValue(
      of({
        results: [{ filename: 'new.xml', outcome: 'created', asset_id: 'a-9' }],
        created_count: 1,
        updated_count: 0,
        skipped_count: 0,
        error_count: 0
      })
    );
    const assetService = fakeAssetService({ executeGlpiImport: executeSpy });
    const fixture = await mount(assetService);
    const component = fixture.componentInstance;

    component.rows = [
      {
        filename: 'new.xml',
        file: file('new.xml'),
        status: 'NEW',
        action: 'create',
        tag: 'PAT-99',
        name: 'HOST-B',
        categoryId: 'cat-1',
        unitId: 'unit-1'
      } as never
    ];

    component.confirmImport();

    expect(executeSpy).toHaveBeenCalledTimes(1);
    const [, decisions] = executeSpy.mock.calls[0];
    expect(decisions).toEqual([
      { filename: 'new.xml', action: 'create', asset_id: undefined, tag: 'PAT-99', name: 'HOST-B', category_id: 'cat-1', unit_id: 'unit-1' }
    ]);
    expect(component.importStep).toBe(3);
    expect(component.resultCreated).toBe(1);
  });

  it('ignores files whose name is already selected, since decisions are matched by filename', async () => {
    const fixture = await mount(fakeAssetService());
    const component = fixture.componentInstance;

    const pick = (...files: File[]) => {
      const input = { files, value: 'x' } as unknown as HTMLInputElement;
      component.onFilesSelected({ target: input } as unknown as Event);
    };

    pick(file('a.xml'), file('b.xml'));
    pick(file('a.xml'), file('c.xml'), file('c.xml'));

    expect(component.selectedFiles.map((f) => f.name)).toEqual(['a.xml', 'b.xml', 'c.xml']);
  });
});

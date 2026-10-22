import { ChangeDetectorRef, Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import {
  AssetCategory,
  AssetService,
  GlpiImportDecision,
  GlpiRowAction,
  GlpiRowOutcome,
  GlpiRowStatus
} from '../../../core/services/asset.service';
import { OrganizationService, Unit } from '../../../core/services/organization.service';

interface ImportRowState {
  filename: string;
  file: File;
  status: GlpiRowStatus;
  errorMessage?: string | null;
  hostname?: string | null;
  serialNumber?: string | null;
  cpuName?: string | null;
  ramMb?: number | null;
  osName?: string | null;
  macAddress?: string | null;
  storageSummary?: string | null;
  suggestedName?: string | null;
  matchedAssetId?: string | null;
  matchedAssetTag?: string | null;
  matchedAssetName?: string | null;
  action: GlpiRowAction;
  tag: string;
  name: string;
  categoryId: string;
  unitId: string;
  outcome?: GlpiRowOutcome;
  outcomeError?: string | null;
}

@Component({
  selector: 'app-asset-glpi-import',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatFormFieldModule,
    MatSelectModule,
    MatSnackBarModule
  ],
  templateUrl: './asset-glpi-import.component.html',
  styleUrls: ['./asset-glpi-import.component.scss']
})
export class AssetGlpiImportComponent {
  private assetService = inject(AssetService);
  private orgService = inject(OrganizationService);
  private router = inject(Router);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  importStep = 1;

  selectedFiles: File[] = [];
  analyzing = false;

  rows: ImportRowState[] = [];
  executing = false;

  categories: AssetCategory[] = [];
  units: Unit[] = [];

  resultCreated = 0;
  resultUpdated = 0;
  resultSkipped = 0;
  resultErrors = 0;

  constructor() {
    this.assetService.getCategories().subscribe({
      next: (cats) => {
        this.categories = cats;
        this.cdr.markForCheck();
      },
      error: (err) => console.error('Erro ao carregar categorias:', err)
    });
    this.orgService.getUnits().subscribe({
      next: (units) => {
        this.units = units;
        this.cdr.markForCheck();
      },
      error: (err) => console.error('Erro ao carregar unidades:', err)
    });
  }

  onFilesSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const incoming = input.files ? Array.from(input.files) : [];
    input.value = '';

    // O servidor casa as decisões pelo nome do arquivo: dois arquivos com o mesmo nome se confundiriam.
    const names = new Set(this.selectedFiles.map((f) => f.name));
    const accepted: File[] = [];
    const ignored: string[] = [];
    for (const file of incoming) {
      if (names.has(file.name)) {
        ignored.push(file.name);
      } else {
        names.add(file.name);
        accepted.push(file);
      }
    }
    this.selectedFiles = [...this.selectedFiles, ...accepted];
    if (ignored.length > 0) {
      this.snackBar.open(`Ignorado(s) por já existir arquivo com o mesmo nome: ${ignored.join(', ')}`, 'Fechar', { duration: 6000 });
    }
  }

  removeFile(file: File): void {
    this.selectedFiles = this.selectedFiles.filter((f) => f !== file);
  }

  formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  private formatStorage(storage?: { model?: string; size_mb?: number; type?: string }[] | null): string | null {
    if (!storage || storage.length === 0) return null;
    return storage
      .map((disk) => {
        const label = disk.model || disk.type || 'Disco';
        const extra = [disk.size_mb ? `${Math.round(disk.size_mb / 1024)} GB` : null, disk.type].filter(Boolean);
        return extra.length ? `${label} (${extra.join(', ')})` : label;
      })
      .join('; ');
  }

  analyzeFiles(): void {
    if (this.selectedFiles.length === 0) return;
    this.analyzing = true;

    this.assetService.analyzeGlpiImport(this.selectedFiles).subscribe({
      next: (res) => {
        this.analyzing = false;
        this.rows = res.rows.map((row) => {
          const file = this.selectedFiles.find((f) => f.name === row.filename)!;
          const defaultAction: GlpiRowAction =
            row.status === 'MATCHED' ? 'update' : row.status === 'NEW' ? 'create' : 'skip';
          return {
            filename: row.filename,
            file,
            status: row.status,
            errorMessage: row.error_message,
            hostname: row.parsed?.hostname,
            serialNumber: row.serial_number,
            cpuName: row.parsed?.cpu_name,
            ramMb: row.parsed?.ram_mb,
            osName: row.parsed?.os_name,
            macAddress: row.parsed?.network?.mac,
            storageSummary: this.formatStorage(row.parsed?.storage),
            suggestedName: row.suggested_name,
            matchedAssetId: row.matched_asset_id,
            matchedAssetTag: row.matched_asset_tag,
            matchedAssetName: row.matched_asset_name,
            action: defaultAction,
            tag: '',
            name: row.suggested_name || row.filename,
            categoryId: '',
            unitId: ''
          };
        });
        this.importStep = 2;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.analyzing = false;
        const msg = err.error?.error?.message || 'Erro ao analisar os arquivos enviados.';
        this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        this.cdr.markForCheck();
      }
    });
  }

  isRowValid(row: ImportRowState): boolean {
    if (row.action === 'skip') return true;
    if (row.action === 'update') return !!row.matchedAssetId;
    return !!row.tag && !!row.categoryId && !!row.unitId;
  }

  get canConfirm(): boolean {
    return this.rows.length > 0 && this.rows.every((r) => this.isRowValid(r));
  }

  confirmImport(): void {
    if (!this.canConfirm) return;
    this.executing = true;

    const decisions: GlpiImportDecision[] = this.rows.map((row) => ({
      filename: row.filename,
      action: row.action,
      asset_id: row.action === 'update' ? row.matchedAssetId : undefined,
      tag: row.action === 'create' ? row.tag : undefined,
      name: row.action === 'create' ? row.name : undefined,
      category_id: row.action === 'create' ? row.categoryId : undefined,
      unit_id: row.action === 'create' ? row.unitId : undefined
    }));

    this.assetService.executeGlpiImport(this.rows.map((r) => r.file), decisions).subscribe({
      next: (res) => {
        this.executing = false;
        this.resultCreated = res.created_count;
        this.resultUpdated = res.updated_count;
        this.resultSkipped = res.skipped_count;
        this.resultErrors = res.error_count;

        const outcomeByFilename = new Map(res.results.map((r) => [r.filename, r]));
        this.rows.forEach((row) => {
          const result = outcomeByFilename.get(row.filename);
          row.outcome = result?.outcome;
          row.outcomeError = result?.error_message;
        });

        this.importStep = 3;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.executing = false;
        const msg = err.error?.error?.message || 'Erro ao executar a importação.';
        this.snackBar.open(msg, 'Fechar', { duration: 5000 });
        this.cdr.markForCheck();
      }
    });
  }

  resetWizard(): void {
    this.importStep = 1;
    this.selectedFiles = [];
    this.rows = [];
    this.resultCreated = 0;
    this.resultUpdated = 0;
    this.resultSkipped = 0;
    this.resultErrors = 0;
  }

  goToAssets(): void {
    this.router.navigate(['/assets']);
  }
}

import { ChangeDetectorRef, Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';

import { Asset, AssetService } from '../../../core/services/asset.service';
import { AssetQuickViewDialogComponent } from '../asset-quick-view-dialog/asset-quick-view-dialog.component';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';
import { apiErrorMessage } from '../../../core/http/api-error';

@Component({
  selector: 'app-asset-list',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatFormFieldModule,
    MatTooltipModule,
    MatDialogModule,
    LoadStateComponent
  ],
  templateUrl: './asset-list.component.html',
  styleUrls: ['./asset-list.component.scss']
})
export class AssetListComponent implements OnInit {
  private assetService = inject(AssetService);
  private cdr = inject(ChangeDetectorRef);
  private dialog = inject(MatDialog);

  displayedColumns: string[] = ['tag', 'name', 'category', 'unit', 'employee', 'status', 'actions'];
  dataSource = new MatTableDataSource<Asset>([]);
  loading = true;
  loadError: string | null = null;

  ngOnInit(): void {
    this.loadAssets();
  }

  loadAssets(): void {
    this.loading = true;
    this.loadError = null;
    this.assetService.getAssets().subscribe({
      next: (data) => {
        this.loading = false;
        this.dataSource.data = data;
        this.cdr.markForCheck();
        this.dataSource.filterPredicate = (asset: Asset, filter: string) => {
          const searchStr = `${asset.tag} ${asset.name} ${asset.category?.name || ''} ${asset.unit?.name || ''} ${asset.employee?.name || ''}`.toLowerCase();
          return searchStr.includes(filter);
        };
      },
      error: (err) => {
        // falha de comunicação não pode parecer "nenhum ativo registrado"
        this.loading = false;
        this.loadError = apiErrorMessage(err, 'Não foi possível carregar os ativos.');
        this.cdr.markForCheck();
      }
    });
  }

  applyFilter(event: Event): void {
    const filterValue = (event.target as HTMLInputElement).value;
    this.dataSource.filter = filterValue.trim().toLowerCase();
  }

  openQuickView(asset: Asset, event?: Event): void {
    if (event) {
      event.stopPropagation();
    }
    this.dialog.open(AssetQuickViewDialogComponent, {
      data: { asset },
      width: '680px',
      maxWidth: '95vw',
      autoFocus: false
    });
  }

  getStatusBadgeClass(status: string): string {
    switch (status) {
      case 'IN_STOCK':
        return 'badge-stock';
      case 'RESERVED':
        return 'badge-reserved';
      case 'IN_USE':
        return 'badge-use';
      case 'PENDING_INSPECTION':
        return 'badge-inspection';
      case 'MAINTENANCE':
        return 'badge-maint';
      case 'DECOMMISSIONED':
        return 'badge-decom';
      default:
        return 'badge-default';
    }
  }

  getStatusLabel(status: string): string {
    switch (status) {
      case 'IN_STOCK':
        return 'Em Estoque';
      case 'RESERVED':
        return 'Reservado';
      case 'IN_USE':
        return 'Em Uso';
      case 'PENDING_INSPECTION':
        return 'Aguardando Inspeção';
      case 'MAINTENANCE':
        return 'Manutenção';
      case 'DECOMMISSIONED':
        return 'Baixado';
      default:
        return status;
    }
  }

  printResponsibilityStatement(assetId: string, event: Event): void {
    event.stopPropagation();
    this.assetService.openResponsibilityStatement(assetId);
  }
}

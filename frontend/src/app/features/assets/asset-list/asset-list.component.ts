import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatTooltipModule } from '@angular/material/tooltip';

import { Asset, AssetService } from '../../../core/services/asset.service';

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
    MatTooltipModule
  ],
  templateUrl: './asset-list.component.html',
  styleUrls: ['./asset-list.component.scss']
})
export class AssetListComponent implements OnInit {
  private assetService = inject(AssetService);

  displayedColumns: string[] = ['tag', 'name', 'category', 'status', 'actions'];
  dataSource = new MatTableDataSource<Asset>([]);

  ngOnInit(): void {
    this.loadAssets();
  }

  loadAssets(): void {
    this.assetService.getAssets().subscribe({
      next: (data) => {
        this.dataSource.data = data;
        this.dataSource.filterPredicate = (asset: Asset, filter: string) => {
          const searchStr = `${asset.tag} ${asset.name} ${asset.category?.name || ''}`.toLowerCase();
          return searchStr.includes(filter);
        };
      },
      error: (err) => console.error('Erro ao carregar ativos:', err)
    });
  }

  applyFilter(event: Event): void {
    const filterValue = (event.target as HTMLInputElement).value;
    this.dataSource.filter = filterValue.trim().toLowerCase();
  }

  getStatusBadgeClass(status: string): string {
    switch (status) {
      case 'IN_STOCK':
        return 'badge-stock';
      case 'IN_USE':
        return 'badge-use';
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
      case 'IN_USE':
        return 'Em Uso';
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

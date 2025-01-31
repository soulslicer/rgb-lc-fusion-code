import torch.nn as nn
import torch.nn.functional as F
import torch
import utils.img_utils as img_utils
from .loss_blocks import *


class BaseLoss(nn.modules.Module):
    def __init__(self, cfg, id):
        super(BaseLoss, self).__init__()
        self.cfg = cfg
        self.id = id

    def forward(self, output, target):
        output_left, output_right = output
        target_left, target_right = target

        # Extract Variables
        device = output_left["output"][-1].device
        d_candi = target_left["d_candi"]
        T_left2right = target_left["T_left2right"]
        BV_cur_left_array = output_left["output"]
        BV_cur_right_array = output_right["output"]
        BV_cur_refined_left_array = output_left["output_refined"]
        BV_cur_refined_right_array = output_right["output_refined"]
        gt_input_left = target_left
        gt_input_right = target_right

        # NLL Loss for Low Res
        ce_loss = 0
        ce_count = 0
        for ind in range(len(BV_cur_left_array)):
            BV_cur_left = BV_cur_left_array[ind]
            BV_cur_right = BV_cur_right_array[ind]
            for ibatch in range(BV_cur_left.shape[0]):
                ce_count += 1
                # Left Losses
                ce_loss = ce_loss + soft_cross_entropy_loss(
                    gt_input_left["soft_labels"][ibatch].unsqueeze(0),
                    BV_cur_left[ibatch, :, :, :].unsqueeze(0),
                    mask=gt_input_left["masks"][ibatch, :, :, :],
                    BV_log=True)
                # Right Losses
                ce_loss = ce_loss + soft_cross_entropy_loss(
                    gt_input_right["soft_labels"][ibatch].unsqueeze(0),
                    BV_cur_right[ibatch, :, :, :].unsqueeze(0),
                    mask=gt_input_right["masks"][ibatch, :, :, :],
                    BV_log=True)

        # NLL Loss for High Res
        for ind in range(len(BV_cur_refined_left_array)):
            BV_cur_refined_left = BV_cur_refined_left_array[ind]
            BV_cur_refined_right = BV_cur_refined_right_array[ind]
            for ibatch in range(BV_cur_refined_left.shape[0]):
                ce_count += 1
                # Left Losses
                ce_loss = ce_loss + soft_cross_entropy_loss(
                    gt_input_left["soft_labels_imgsize"][ibatch].unsqueeze(0),
                    BV_cur_refined_left[ibatch, :, :, :].unsqueeze(0),
                    mask=gt_input_left["masks_imgsizes"][ibatch, :, :, :],
                    BV_log=True)
                # Right Losses
                ce_loss = ce_loss + soft_cross_entropy_loss(
                    gt_input_right["soft_labels_imgsize"][ibatch].unsqueeze(0),
                    BV_cur_refined_right[ibatch, :, :, :].unsqueeze(0),
                    mask=gt_input_right["masks_imgsizes"][ibatch, :, :, :],
                    BV_log=True)

        # Get Last BV_cur
        BV_cur_left = BV_cur_left_array[-1]
        BV_cur_right = BV_cur_right_array[-1]
        BV_cur_refined_left = BV_cur_refined_left_array[-1]
        BV_cur_refined_right = BV_cur_refined_right_array[-1]

        # Regress all depthmaps once here
        small_dm_left_arr = []
        large_dm_left_arr = []
        small_dm_right_arr = []
        large_dm_right_arr = []
        for ibatch in range(BV_cur_left.shape[0]):
            small_dm_left_arr.append(
                img_utils.dpv_to_depthmap(BV_cur_left[ibatch, :, :, :].unsqueeze(0), d_candi, BV_log=True))
            large_dm_left_arr.append(
                img_utils.dpv_to_depthmap(BV_cur_refined_left[ibatch, :, :, :].unsqueeze(0), d_candi, BV_log=True))
            small_dm_right_arr.append(
                img_utils.dpv_to_depthmap(BV_cur_right[ibatch, :, :, :].unsqueeze(0), d_candi, BV_log=True))
            large_dm_right_arr.append(
                img_utils.dpv_to_depthmap(BV_cur_refined_right[ibatch, :, :, :].unsqueeze(0), d_candi, BV_log=True))

        # Downsample Consistency Loss (Should we even have a mask here?)
        dc_loss = 0
        for ibatch in range(BV_cur_left.shape[0]):
            if self.cfg.loss.dc_mul == 0: break
            # Left
            mask_left = gt_input_left["masks"][ibatch, :, :, :]
            small_dm_left = small_dm_left_arr[ibatch]
            large_dm_left = large_dm_left_arr[ibatch]
            dc_loss = dc_loss + depth_consistency_loss(large_dm_left, small_dm_left)
            # Right
            mask_right = gt_input_right["masks"][ibatch, :, :, :]
            small_dm_right = small_dm_right_arr[ibatch]
            large_dm_right = large_dm_right_arr[ibatch]
            dc_loss = dc_loss + depth_consistency_loss(large_dm_right, small_dm_right)

        # Depth Stereo Consistency Loss
        pose_target2src = T_left2right
        pose_target2src = torch.unsqueeze(pose_target2src, 0).to(device)
        pose_src2target = torch.inverse(T_left2right)
        pose_src2target = torch.unsqueeze(pose_src2target, 0).to(device)
        dsc_loss = 0
        for ibatch in range(BV_cur_left.shape[0]):
            if self.cfg.loss.dsc_mul == 0: break
            # Get all Data
            intr_up_left = gt_input_left["intrinsics_up"][ibatch, :, :].unsqueeze(0)
            intr_left = gt_input_left["intrinsics"][ibatch, :, :].unsqueeze(0)
            intr_up_right = gt_input_right["intrinsics_up"][ibatch, :, :].unsqueeze(0)
            intr_right = gt_input_right["intrinsics"][ibatch, :, :].unsqueeze(0)
            depth_up_left = large_dm_left_arr[ibatch].unsqueeze(0)
            depth_left = small_dm_left_arr[ibatch].unsqueeze(0)
            depth_up_right = large_dm_right_arr[ibatch].unsqueeze(0)
            depth_right = small_dm_right_arr[ibatch].unsqueeze(0)
            mask_up_left = gt_input_left["masks_imgsizes"][ibatch, :, :, :]
            mask_left = gt_input_left["masks"][ibatch, :, :, :]
            mask_up_right = gt_input_right["masks_imgsizes"][ibatch, :, :, :]
            mask_right = gt_input_right["masks"][ibatch, :, :, :]
            # Right to Left
            dsc_loss = dsc_loss + depth_stereo_consistency_loss(depth_up_right, depth_up_left, mask_up_right,
                                                                mask_up_left,
                                                                pose_target2src, intr_up_left)
            dsc_loss = dsc_loss + depth_stereo_consistency_loss(depth_right, depth_left, mask_right, mask_left,
                                                                pose_target2src, intr_left)
            # Left to Right
            dsc_loss = dsc_loss + depth_stereo_consistency_loss(depth_up_left, depth_up_right, mask_up_left,
                                                                mask_up_right,
                                                                pose_src2target, intr_up_right)
            dsc_loss = dsc_loss + depth_stereo_consistency_loss(depth_left, depth_right, mask_left, mask_right,
                                                                pose_src2target, intr_right)

        # RGB Stereo Consistency Loss (Just on high res)
        rsc_loss = 0
        for ibatch in range(BV_cur_left.shape[0]):
            if self.cfg.loss.rsc_mul == 0: break
            intr_up_left = gt_input_left["intrinsics_up"][ibatch, :, :].unsqueeze(0)
            intr_up_right = gt_input_right["intrinsics_up"][ibatch, :, :].unsqueeze(0)
            depth_up_left = large_dm_left_arr[ibatch]
            depth_up_right = large_dm_right_arr[ibatch]
            rgb_up_left = gt_input_left["rgb"][ibatch, -1, :, :, :].unsqueeze(0)
            rgb_up_right = gt_input_right["rgb"][ibatch, -1, :, :, :].unsqueeze(0)
            mask_up_left = gt_input_left["masks_imgsizes"][ibatch, :, :, :]
            mask_up_right = gt_input_right["masks_imgsizes"][ibatch, :, :, :]
            # Right to Left
            # src_rgb_img, target_rgb_img, target_depth_map, pose_target2src, intr
            rsc_loss = rsc_loss + rgb_stereo_consistency_loss(rgb_up_right, rgb_up_left, depth_up_left,
                                                              pose_target2src,
                                                              intr_up_left)
            # Left to Right
            rsc_loss = rsc_loss + rgb_stereo_consistency_loss(rgb_up_left, rgb_up_right, depth_up_right,
                                                              pose_src2target,
                                                              intr_up_right)

        # RGB Stereo Consistency Loss (Low res)
        rsc_low_loss = 0
        for ibatch in range(BV_cur_left.shape[0]):
            if self.cfg.loss.rsc_low_mul == 0: break
            intr_left = gt_input_left["intrinsics"][ibatch, :, :].unsqueeze(0)
            intr_right = gt_input_right["intrinsics"][ibatch, :, :].unsqueeze(0)
            depth_left = small_dm_left_arr[ibatch]
            depth_right = small_dm_right_arr[ibatch]
            rgb_left = F.interpolate(gt_input_left["rgb"][ibatch, -1, :, :, :].unsqueeze(0), scale_factor=0.25,
                                     mode='bilinear')
            rgb_right = F.interpolate(gt_input_right["rgb"][ibatch, -1, :, :, :].unsqueeze(0), scale_factor=0.25,
                                      mode='bilinear')
            # Right to Left
            # src_rgb_img, target_rgb_img, target_depth_map, pose_target2src, intr
            rsc_low_loss = rsc_low_loss + rgb_stereo_consistency_loss(rgb_right, rgb_left, depth_left,
                                                                      pose_target2src,
                                                                      intr_left)
            # Left to Right
            rsc_low_loss = rsc_low_loss + rgb_stereo_consistency_loss(rgb_left, rgb_right, depth_right,
                                                                      pose_src2target,
                                                                      intr_right)

        # Smoothness loss (Just on high res)
        smooth_loss = 0
        for ibatch in range(BV_cur_left.shape[0]):
            if self.cfg.loss.smooth_mul == 0: break
            depth_up_left = large_dm_left_arr[ibatch].unsqueeze(0)
            depth_up_right = large_dm_right_arr[ibatch].unsqueeze(0)
            rgb_up_left = gt_input_left["rgb"][ibatch, -1, :, :, :].unsqueeze(0)
            rgb_up_right = gt_input_right["rgb"][ibatch, -1, :, :, :].unsqueeze(0)
            # Left
            smooth_loss = smooth_loss + edge_aware_smoothness_loss([depth_up_left], rgb_up_left, 1)
            # Right
            smooth_loss = smooth_loss + edge_aware_smoothness_loss([depth_up_right], rgb_up_right, 1)

        # All Loss
        loss = torch.tensor(0.).to(device)

        # Depth Losses
        bsize = torch.tensor(float(BV_cur_left.shape[0] * 2)).to(device)
        if bsize != 0:
            ce_loss = (ce_loss / ce_count) * self.cfg.loss.ce_mul
            dsc_loss = (dsc_loss / bsize) * self.cfg.loss.dsc_mul
            dc_loss = (dc_loss / bsize) * self.cfg.loss.dc_mul
            rsc_loss = (rsc_loss / bsize) * self.cfg.loss.rsc_mul
            rsc_low_loss = (rsc_low_loss / bsize) * self.cfg.loss.rsc_low_mul
            smooth_loss = (smooth_loss / bsize) * self.cfg.loss.smooth_mul
            loss += (ce_loss + dsc_loss + dc_loss + rsc_loss + rsc_low_loss + smooth_loss)

        return loss

class DefaultLoss(nn.modules.Module):
    def __init__(self, cfg, id):
        super(DefaultLoss, self).__init__()
        self.cfg = cfg
        self.id = id

    def forward(self, output, target):
        """
        :param output: Multi-scale forward/backward flows n * [B x 4 x h x w]
        :param target: image pairs Nx6xHxW
        :return:
        """

        output_left, output_right = output
        target_left, target_right = target

        left_loss = 0.
        right_loss = 0.
        for b in range(0, len(target_left["soft_labels"])):
            label_left = target_left["soft_labels"][b].unsqueeze(0)
            label_right = target_right["soft_labels"][b].unsqueeze(0)

            left_loss += torch.sum(torch.abs(output_left["output"][-1] - 0))
            right_loss += torch.sum(torch.abs(output_right["output"][-1] - 0))

        loss = left_loss + right_loss

        return loss

class SweepLoss(nn.modules.Module):
    def __init__(self, cfg, id):
        super(SweepLoss, self).__init__()
        self.cfg = cfg
        self.id = id

    def loss(self, output, depth, feat_int, feat_masks, masks, d_candi):
        # Iterate Batch
        loss = 0.
        for i in range(0, output.shape[0]):

            # Ignore data who is nothing
            feat_mask = feat_masks[i,:,:,:].float()
            mask = masks[i,:,:,:].float()
            if(torch.sum(feat_mask) == 0):
                continue

            # # Run Model
            # mean_intensities, DPV = img_utils.lc_intensities_to_dist(
            #     d_candi = d_candi, 
            #     placement = depth[i,:,:].unsqueeze(-1), 
            #     intensity = 0, 
            #     inten_sigma = output[i, 1, :, :].unsqueeze(-1), # Change
            #     noise_sigma = 0.1, 
            #     mean_scaling = output[i, 0, :, :].unsqueeze(-1)) # Change
            # mean_intensities = mean_intensities.permute(2,0,1) # 128, 256, 320

            # # Compute Error
            model_loss = 0
            # gt = feat_int[i,:,:,:] / 255.
            # pred = mean_intensities * 1
            # model_count = torch.sum(feat_mask)
            # model_loss = (torch.sum(((gt-pred)**2)*feat_mask) / model_count)

            # # L1 image error
            # img_count = torch.sum(mask)
            # peak_gt = torch.max(feat_int[i, :, :, :], dim=0)[0] / 255.
            # peak_pred = output[i, 0, :, :] * 1
            # img_loss = torch.sum(torch.abs(peak_gt - peak_pred)*mask.squeeze(0)) / img_count

            # MSLE error
            img_count = torch.sum(mask)
            peak_gt = torch.max(feat_int[i, :, :, :], dim=0)[0] / 255.
            peak_pred = output[i, 0, :, :] * 1
            peak_gt = peak_gt*mask.squeeze(0)
            peak_pred = peak_pred*mask.squeeze(0)
            img_loss = torch.sqrt(torch.sum((torch.log(peak_gt + img_utils.epsilon) - torch.log(peak_pred + img_utils.epsilon))**2) / img_count)

            # print(model_count, model_loss, img_loss)

            loss += ((model_loss*self.cfg.loss.model_mult + img_loss*self.cfg.loss.img_mult) / 1)

        return loss

    def loss_function(self, output, target):

        # Get Large Params
        output_large = output["output_refined"][0] # 1, 2, 256, 320
        depth_map_large = target["dmap_imgsizes"] # 1, 256, 320
        feat_int_tensor_large = target["feat_int_tensor"] # 1, 128, 256, 320
        feat_mask_tensor_large = target["feat_mask_tensor"] # 1, 128, 256, 320
        mask_tensor_large = target["mask_tensor"] # 1, 128, 256, 320
        d_candi = torch.tensor(target["d_candi"]).float().to(output_large.device) # Double check that this is correct

        # Loss
        large_loss = self.loss(output_large, depth_map_large, feat_int_tensor_large, feat_mask_tensor_large, mask_tensor_large, d_candi)

        # Generate Small Params
        output_small = output["output"][0] # 1, 2, 64, 80
        depth_map_small = target["dmaps"] # 1, 64, 80
        feat_int_tensor_small = F.interpolate(feat_int_tensor_large, size=[int(feat_int_tensor_large.shape[2]/4), int(feat_int_tensor_large.shape[3]/4)], mode='nearest')
        feat_mask_tensor_small = F.interpolate(feat_mask_tensor_large, size=[int(feat_int_tensor_large.shape[2]/4), int(feat_int_tensor_large.shape[3]/4)], mode='nearest')
        mask_tensor_small = F.interpolate(mask_tensor_large, size=[int(feat_int_tensor_large.shape[2]/4), int(feat_int_tensor_large.shape[3]/4)], mode='nearest')

        # Loss
        small_loss = self.loss(output_small, depth_map_small, feat_int_tensor_small, feat_mask_tensor_small, mask_tensor_small, d_candi)

        return (large_loss + small_loss)

    def forward(self, output, target):
        output_left, output_right = output
        target_left, target_right = target
        device = output_left["output_refined"][0].device
        bsize = torch.tensor(float(output_left["output_refined"][0].shape[0] * 2)).to(device)
        T_left2right = target_left["T_left2right"]

        left_loss = self.loss_function(output_left, target_left)
        right_loss = self.loss_function(output_right, target_right)
        
        # Consistency Loss (Just on high res)
        pose_target2src = T_left2right
        pose_target2src = torch.unsqueeze(pose_target2src, 0).to(device)
        pose_src2target = torch.inverse(T_left2right)
        pose_src2target = torch.unsqueeze(pose_src2target, 0).to(device)
        c_loss = 0
        # for ibatch in range(int(bsize.item()/2)):
        #     #if self.cfg.loss.rsc_mul == 0: break
        #     intr_up_left = target_left["intrinsics_up"][ibatch, :, :].unsqueeze(0)
        #     intr_up_right = target_right["intrinsics_up"][ibatch, :, :].unsqueeze(0)
        #     depth_up_left = target_left["dmap_imgsizes"][ibatch, :, :].unsqueeze(0)
        #     depth_up_right = target_right["dmap_imgsizes"][ibatch, :, :].unsqueeze(0)
        #     rgb_up_left = output_left["output_refined"][0][ibatch, :, :, :].unsqueeze(0)
        #     rgb_up_right = output_right["output_refined"][0][ibatch, :, :, :].unsqueeze(0)
        #     feat_mask_left = target_left["feat_mask_tensor"][ibatch, :, :]
        #     feat_mask_right = target_right["feat_mask_tensor"][ibatch, :, :]
        #     if(torch.sum(feat_mask_left) == 0 or torch.sum(feat_mask_right) == 0):
        #         continue
        #     if(torch.sum(depth_up_left) == 0 or torch.sum(depth_up_right) == 0):
        #         continue

        #     # Right to Left
        #     # src_rgb_img, target_rgb_img, target_depth_map, pose_target2src, intr
        #     c_loss = c_loss + lc_stereo_consistency_loss(rgb_up_right, rgb_up_left, depth_up_left,
        #                                                       pose_target2src,
        #                                                       intr_up_left)
        #     # Left to Right
        #     c_loss = c_loss + lc_stereo_consistency_loss(rgb_up_left, rgb_up_right, depth_up_right,
        #                                                       pose_src2target,
        #                                                       intr_up_right)

        # # print(c_loss)
        
        loss = (left_loss + right_loss + c_loss*self.cfg.loss.c_mult)

        if(torch.isnan(loss)):
            stop

        return (loss / bsize)
